import socket
import os
import sys
import threading
import zipfile
import shutil


class FTPServer:
    def __init__(self, address="", listen_port=2100):
        self.address = address
        self.listen_port = listen_port
        self.ctrl_socket = None
        self.data_listener = None
        self.data_channel = None
        self.active = False
        self.working_dir = os.getcwd()
        self.mode = "A"

    def launch(self):
        self.ctrl_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.ctrl_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.ctrl_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        self.ctrl_socket.bind(("::", self.listen_port))
        self.ctrl_socket.listen(5)
        self.active = True
        print(f"FTP Server started on port {self.listen_port}")

        while self.active:
            conn, client_addr = self.ctrl_socket.accept()
            print(f"New client: {client_addr}")
            thread = threading.Thread(target=self._client_session, args=(conn,))
            thread.start()

    def _reply(self, sock, code, msg):
        resp = f"{code} {msg}\r\n"
        sock.sendall(resp.encode())
        print(f"Sent: {code} {msg}")

    def _client_session(self, sock):
        self._reply(sock, 220, "Hello! Connected to Simple FTP Service.")

        while True:
            try:
                incoming = sock.recv(1024).decode().strip()
                if not incoming:
                    break

                print(f"Received: {incoming}")
                cmd, *params = incoming.split(" ", 1)
                cmd = cmd.upper()
                arg = params[0] if params else ""

                handler = getattr(self, f"_handle_{cmd}", self._handle_UNKNOWN)
                if not handler(sock, arg):
                    break

            except Exception as exc:
                print(f"Session error: {exc}")
                break

        print("Client disconnected")
        sock.close()
        if self.data_channel:
            self.data_channel.close()

    def _handle_USER(self, sock, arg):
        self._reply(sock, 331, "User OK, need password.")
        return True

    def _handle_PASS(self, sock, arg):
        self._reply(sock, 230, "Login OK.")
        return True

    def _handle_SYST(self, sock, arg):
        self._reply(sock, 215, "UNIX Type: L8")
        return True

    def _handle_FEAT(self, sock, arg):
        features = "211-Features:\r\n UTF8\r\n"
        sock.sendall(features.encode())
        self._reply(sock, 211, "End of features.")
        return True

    def _handle_PWD(self, sock, arg):
        self._reply(sock, 257, f'"{self.working_dir}" is your current directory.')
        return True

    def _handle_XPWD(self, sock, arg):
        return self._handle_PWD(sock, arg)

    def _handle_TYPE(self, sock, arg):
        t = arg.split(" ")[0] if arg else ""
        if t in ["A", "I"]:
            self.mode = t
            self._reply(sock, 200, f"Type set to {t}")
        else:
            self._reply(sock, 504, "Unsupported type.")
        return True

    def _handle_PASV(self, sock, arg):
        if self.data_channel:
            self.data_channel.close()

        self.data_channel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.data_channel.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.data_channel.bind(("0.0.0.0", 0))
        self.data_channel.listen(1)

        ip = "127.0.0.1"
        port = self.data_channel.getsockname()[1]
        print(f"Passive mode: {ip}:{port}")

        ip_nums = list(map(int, ip.split(".")))
        port_nums = [port >> 8, port & 0xFF]
        msg = f"Entering Passive Mode ({','.join(map(str, ip_nums + port_nums))})"
        self._reply(sock, 227, msg)
        return True

    def _handle_EPSV(self, sock, arg):
        if self.data_channel:
            self.data_channel.close()

        ipv6 = ":" in sock.getpeername()[0]
        family = socket.AF_INET6 if ipv6 else socket.AF_INET
        bind_addr = "::" if ipv6 else "0.0.0.0"

        self.data_channel = socket.socket(family, socket.SOCK_STREAM)
        self.data_channel.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.data_channel.bind((bind_addr, 0))
        self.data_channel.listen(1)

        port = self.data_channel.getsockname()[1]
        print(f"EPSV: port {port}")

        self._reply(sock, 229, f"Extended Passive Mode (|||{port}|)")
        return True

    def _handle_CWD(self, sock, arg):
        try:
            if os.path.isdir(arg):
                os.chdir(arg)
                self.working_dir = os.getcwd()
                self._reply(sock, 250, f"Directory changed to {arg}")
            else:
                self._reply(sock, 550, f"Directory '{arg}' not found.")
        except Exception as exc:
            self._reply(sock, 550, f"Change dir error: {str(exc)}")
        return True

    def _handle_LIST(self, sock, arg):
        if self.data_channel:
            self._reply(sock, 150, "Listing directory...")
            try:
                data_conn, addr = self.data_channel.accept()
                print(f"Data link: {addr}")

                files = os.listdir(self.working_dir)
                lines = []
                for fname in files:
                    fpath = os.path.join(self.working_dir, fname)
                    stats = os.stat(fpath)
                    ftype = "d" if os.path.isdir(fpath) else "-"
                    size = stats.st_size
                    perms = "rwxrwxrwx"
                    entry = f"{ftype}{perms} 1 owner group {size} Jan 1 00:00 {fname}"
                    lines.append(entry)

                data = "\r\n".join(lines) + "\r\n"
                data_conn.sendall(data.encode())
                data_conn.close()
                self._reply(sock, 226, "Directory sent.")
            except Exception as exc:
                self._reply(sock, 425, f"LIST error: {str(exc)}")
            finally:
                self.data_channel.close()
                self.data_channel = None
        else:
            self._reply(sock, 425, "Enable PASV/EPSV first.")
        return True

    def _handle_NLST(self, sock, arg):
        if self.data_channel:
            self._reply(sock, 150, "NLST sending...")
            try:
                data_conn, addr = self.data_channel.accept()
                print(f"Data link: {addr}")

                files = os.listdir(self.working_dir)
                data = "\r\n".join(files) + "\r\n"
                data_conn.sendall(data.encode())
                data_conn.close()
                self._reply(sock, 226, "NLST done.")
            except Exception as exc:
                self._reply(sock, 425, f"NLST error: {str(exc)}")
            finally:
                self.data_channel.close()
                self.data_channel = None
        else:
            self._reply(sock, 425, "Enable PASV/EPSV first.")
        return True

    def _handle_RETR(self, sock, arg):
        if not arg:
            self._reply(sock, 501, "No file for RETR.")
            return True

        fname = arg
        fpath = os.path.join(self.working_dir, fname)

        if not os.path.exists(fpath):
            self._reply(sock, 550, f"File '{fname}' not found.")
            return True

        if self.data_channel:
            self._reply(sock, 150, f"Transferring {fname}...")
            try:
                data_conn, addr = self.data_channel.accept()
                print(f"Data link: {addr}")

                with open(fpath, "rb") as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        data_conn.sendall(chunk)

                data_conn.close()
                self._reply(sock, 226, "Transfer complete.")
            except Exception as exc:
                self._reply(sock, 426, f"RETR error: {str(exc)}")
            finally:
                self.data_channel.close()
                self.data_channel = None
        else:
            self._reply(sock, 425, "Enable PASV/EPSV first.")
        return True

    def _handle_STOR(self, sock, arg):
        if not arg:
            self._reply(sock, 501, "No file for STOR.")
            return True

        fname = arg
        fpath = os.path.join(self.working_dir, fname)

        if self.data_channel:
            self._reply(sock, 150, f"Ready for {fname}...")
            try:
                data_conn, addr = self.data_channel.accept()
                print(f"Data link: {addr}")

                with open(fpath, "wb") as f:
                    while True:
                        chunk = data_conn.recv(8192)
                        if not chunk:
                            break
                        f.write(chunk)

                data_conn.close()
                self._reply(sock, 226, "Upload complete.")
            except Exception as exc:
                self._reply(sock, 426, f"STOR error: {str(exc)}")
            finally:
                self.data_channel.close()
                self.data_channel = None
        else:
            self._reply(sock, 425, "Enable PASV/EPSV first.")
        return True

    def _handle_NOOP(self, sock, arg):
        self._reply(sock, 200, "NOOP OK.")
        return True

    def _handle_QUIT(self, sock, arg):
        self._reply(sock, 221, "Bye.")
        return False

    def _handle_DELE(self, sock, arg):
        if not arg:
            self._reply(sock, 501, "No file for DELE.")
            return True

        fname = arg
        fpath = os.path.join(self.working_dir, fname)

        if not os.path.exists(fpath):
            self._reply(sock, 550, f"File '{fname}' not found.")
            return True

        try:
            os.remove(fpath)
            self._reply(sock, 250, f"Deleted '{fname}'.")
        except Exception as exc:
            self._reply(sock, 550, f"Delete error: {str(exc)}")
        return True

    def _handle_MKD(self, sock, arg):
        if not arg:
            self._reply(sock, 501, "No directory name given.")
            return True

        dname = arg
        dpath = os.path.join(self.working_dir, dname)

        try:
            os.makedirs(dpath, exist_ok=False)
            self._reply(sock, 257, f'"{dname}" directory created.')
        except FileExistsError:
            self._reply(sock, 550, f"Directory '{dname}' already exists.")
        except Exception as exc:
            self._reply(sock, 550, f"MKD error: {str(exc)}")
        return True

    def _handle_ZIP(self, sock, arg):
        if not arg:
            self._reply(sock, 501, "No file or directory specified for ZIP.")
            return True

        target_path = os.path.join(self.working_dir, arg)
        zip_path = os.path.join(self.working_dir, f"{arg}.zip")

        if not os.path.exists(target_path):
            self._reply(sock, 550, f"Target '{arg}' not found.")
            return True

        try:
            if os.path.isdir(target_path):
                parent_dir = os.path.dirname(target_path)
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    for root, dirs, files in os.walk(target_path):
                        for file in files:
                            abs_path = os.path.join(root, file)
                            rel_path = os.path.relpath(abs_path, parent_dir)
                            zipf.write(abs_path, arcname=rel_path)
            else:
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
                    zipf.write(target_path, arcname=os.path.basename(target_path))
            self._reply(sock, 226, f"Zipped '{arg}' to '{arg}.zip'.")
        except Exception as exc:
            self._reply(sock, 550, f"ZIP error: {str(exc)}")
        return True

    def _handle_UNZIP(self, sock, arg):
        if not arg:
            self._reply(sock, 501, "No zip file specified for UNZIP.")
            return True

        zip_path = os.path.join(self.working_dir, arg)
        if not zip_path.endswith(".zip"):
            zip_path += ".zip"
        if not os.path.exists(zip_path):
            self._reply(sock, 550, f"Zip file '{arg}' not found.")
            return True

        try:
            with zipfile.ZipFile(zip_path, "r") as zipf:
                zipf.extractall(self.working_dir)
            self._reply(sock, 226, f"Unzipped '{os.path.basename(zip_path)}'.")
        except Exception as exc:
            self._reply(sock, 550, f"UNZIP error: {str(exc)}")
        return True

    def _handle_UNKNOWN(self, sock, arg):
        self._reply(sock, 502, "Unknown command.")
        return True


if __name__ == "__main__":
    ftp = FTPServer()
    try:
        ftp.launch()
    except KeyboardInterrupt:
        ftp.active = False
        ftp.ctrl_socket.close()
        print("FTP Service stopped.")
