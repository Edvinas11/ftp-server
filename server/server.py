import socket
import os
import random
import threading

USER_CREDENTIALS = {
    "user": "pass"
}

BASE_DIR = os.path.join(os.getcwd(), 'main')
HOST = '127.0.0.1'
PORT = 20000

def rfc_reply(code, message):
    return f"{code} {message}\r\n"

def handle_client(conn, addr):
    authenticated = False
    current_dir = BASE_DIR
    username = None
    data_socket = None

    conn.sendall(rfc_reply(220, "Simple FTP server ready.").encode())

    while True:
        data = conn.recv(1024).decode().strip()
        if not data:
            break
        print(f"[{addr}] Received: {data}")

        cmd_parts = data.split()
        command = cmd_parts[0].upper()

        if command == "USER":
            username = cmd_parts[1] if len(cmd_parts) > 1 else ""
            if username in USER_CREDENTIALS:
                conn.sendall(rfc_reply(331, "User name okay, need password.").encode())
            else:
                conn.sendall(rfc_reply(530, "User not found.").encode())

        elif command == "PASS":
            password = cmd_parts[1] if len(cmd_parts) > 1 else ""
            if username and USER_CREDENTIALS.get(username) == password:
                authenticated = True
                conn.sendall(rfc_reply(230, "User logged in, proceed.").encode())
            else:
                conn.sendall(rfc_reply(530, "Not logged in.").encode())

        elif not authenticated:
            conn.sendall(rfc_reply(530, "Please login with USER and PASS.").encode())

        elif command == "PWD":
            relative_path = os.path.relpath(current_dir, BASE_DIR)
            conn.sendall(rfc_reply(257, f'"{"/" if relative_path == "." else relative_path}" is the current directory.').encode())

        elif command == "CWD":
            if len(cmd_parts) < 2:
                conn.sendall(rfc_reply(501, "Syntax error in parameters.").encode())
                continue
            target = cmd_parts[1]
            new_path = os.path.abspath(os.path.join(current_dir, target))
            if os.path.commonpath([BASE_DIR, new_path]) != BASE_DIR:
                conn.sendall(rfc_reply(550, "Access denied.").encode())
            elif os.path.isdir(new_path):
                current_dir = new_path
                conn.sendall(rfc_reply(250, "Directory changed successfully.").encode())
            else:
                conn.sendall(rfc_reply(550, "Directory not found.").encode())

        elif command == "LIST":
            if data_socket is None:
                conn.sendall(rfc_reply(425, "Use PASV first.").encode())
                continue
            conn.sendall(b"150 Here comes the directory listing.\r\n")
            client_data, _ = data_socket.accept()
            entries = os.listdir(current_dir)
            for entry in entries:
                client_data.sendall(f"{entry}\r\n".encode())
            client_data.close()
            data_socket.close()
            data_socket = None
            conn.sendall(b"226 Directory send OK.\r\n")

        elif command == "RETR":
            if len(cmd_parts) < 2:
                conn.sendall(rfc_reply(501, "No filename given.").encode())
                continue
            if data_socket is None:
                conn.sendall(rfc_reply(425, "Use PASV first.").encode())
                continue
            filename = cmd_parts[1]
            filepath = os.path.join(current_dir, filename)
            if not os.path.isfile(filepath):
                conn.sendall(rfc_reply(550, "File not found.").encode())
                continue

            conn.sendall(rfc_reply(150, "Opening binary mode data connection.").encode())
            data_conn, _ = data_socket.accept()
            with open(filepath, 'rb') as f:
                data_conn.sendfile(f)
            data_conn.close()
            data_socket.close()
            data_socket = None
            conn.sendall(rfc_reply(226, "Transfer complete.").encode())

        elif command == "STOR":
            if len(cmd_parts) < 2:
                conn.sendall(rfc_reply(501, "No filename given.").encode())
                continue
            if data_socket is None:
                conn.sendall(rfc_reply(425, "Use PASV first.").encode())
                continue
            filename = cmd_parts[1]
            filepath = os.path.join(current_dir, filename)

            conn.sendall(rfc_reply(150, "Opening binary mode data connection for file upload.").encode())
            data_conn, _ = data_socket.accept()
            with open(filepath, 'wb') as f:
                while True:
                    chunk = data_conn.recv(1024)
                    if not chunk:
                        break
                    f.write(chunk)
            data_conn.close()
            data_socket.close()
            data_socket = None
            conn.sendall(rfc_reply(226, "Upload complete.").encode())

        elif command == "PASV":
            if data_socket:
                data_socket.close()
            data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            data_socket.bind((HOST, 0))
            data_socket.listen(1)
            ip, port = data_socket.getsockname()
            ip_parts = ip.split('.')
            p1 = port // 256
            p2 = port % 256
            pasv_response = f"227 Entering Passive Mode ({','.join(ip_parts)},{p1},{p2}).\r\n"
            conn.sendall(pasv_response.encode())

        elif command == "SYST":
            conn.sendall(rfc_reply(215, "UNIX Type: L8").encode())

        elif command == "NOOP":
            conn.sendall(rfc_reply(200, "NOOP ok.").encode())

        elif command == "HELP":
            help_msg = (
                "214-The following commands are recognized:\r\n"
                "USER PASS PWD CWD LIST RETR STOR SYST NOOP HELP QUIT\r\n"
                "214 Help OK.\r\n"
            )
            conn.sendall(help_msg.encode())

        elif command == "QUIT":
            conn.sendall(rfc_reply(221, "Goodbye.").encode())
            break

        else:
            conn.sendall(rfc_reply(502, "Command not implemented.").encode())

    conn.close()
    print(f"[{addr}] Connection closed.")

def main():
    if not os.path.exists(BASE_DIR):
        os.mkdir(BASE_DIR)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((HOST, PORT))
    server_socket.listen()
    print(f"[*] FTP Server listening on {HOST}:{PORT}...")

    while True:
        conn, addr = server_socket.accept()
        print(f"[+] New connection from {addr}")
        threading.Thread(target=handle_client, args=(conn, addr)).start()

if __name__ == "__main__":
    main()
