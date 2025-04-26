import socket
import os
import sys
import threading

class FTPServer:
    def __init__(self, host='', port=2121): # is usually 21
        self.host = host
        self.port = port
        self.server_socket = None
        self.passive_port = None
        self.data_socket = None
        self.running = False
        self.current_path = os.getcwd()
        self.transfer_type = 'A'  # ASCII mode by default

    def start(self):
        self.server_socket = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        self.server_socket.bind(('::', self.port))
        self.server_socket.listen(5) # 5 max conns
        self.running = True
        print(f"FTP Server listening on port {self.port} (both IPv4 and IPv6 are ok)")

        while self.running:
            client_socket, addr = self.server_socket.accept()
            print(f"New connection from {addr}")
            client_handler = threading.Thread(
                target=self.handle_client,
                args=(client_socket,)
            )
            client_handler.start()

    def send_response(self, client_socket, code, message):
        response = f"{code} {message}\r\n"
        client_socket.send(response.encode())
        print(f"Sent: {code} {message}")

    def handle_client(self, client_socket):
        self.send_response(client_socket, 220, "You've successfully connected to the FTP Server")
        
        while True:
            try:
                data = client_socket.recv(1024).decode().strip()
                if not data:
                    break
                
                print(f"Received: {data}")
                command = data.split(' ')[0].upper()
                # command args after a space:
                args = data[len(command):].strip() if len(data) > len(command) else ""

                if command == 'USER':
                    self.send_response(client_socket, 331, "User name okay, need password")
                elif command == 'PASS':
                    self.send_response(client_socket, 230, "User logged in")
                elif command == 'SYST':
                    self.send_response(client_socket, 215, "UNIX Type: L8")
                elif command == 'FEAT':
                    # list supported features
                    features = "211-Features:\r\n UTF8\r\n"
                    client_socket.send(features.encode())
                    self.send_response(client_socket, 211, "End")
                elif command == 'PWD' or command == 'XPWD':
                    self.send_response(client_socket, 257, f'"{self.current_path}" is current directory')
                elif command == 'TYPE':
                    type_code = args.split(' ')[0] if args else ''
                    if type_code in ['A', 'I']: # I is binary, A is text
                        self.transfer_type = type_code
                        self.send_response(client_socket, 200, f"Type set to {type_code}")
                    else:
                        self.send_response(client_socket, 504, "Type not implemented")
                elif command == 'PASV': # passive for ipv4 only
                    # close previous data socket if it exists
                    if self.data_socket:
                        self.data_socket.close()
                    
                    # create new IPv4 data socket for PASV
                    self.data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    self.data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.data_socket.bind(('0.0.0.0', 0)) # 0 tells os to get any available port
                    self.data_socket.listen(1)
                    
                    ip = '127.0.0.1'
                    port = self.data_socket.getsockname()[1]
                    
                    print(f"PASV mode - waiting for connection on {ip}:{port}")
                    
                    # format IP/port for PASV response
                    ip_parts = list(map(int, ip.split('.'))) # some weird ahh formatting shit
                    port_part = [port >> 8, port & 0xFF] # some weird ahh formatting shit
                    pasv_response = f"Entering Passive Mode ({','.join(map(str, ip_parts + port_part))})"
                    self.send_response(client_socket, 227, pasv_response)
                elif command == 'EPSV': # passive but for ipv6
                    # close previous data socket if it exists
                    if self.data_socket:
                        self.data_socket.close()
                    
                    # create appropriate socket type based on client connection
                    is_ipv6 = ':' in client_socket.getpeername()[0]
                    addr_family = socket.AF_INET6 if is_ipv6 else socket.AF_INET
                    bind_addr = '::' if is_ipv6 else '0.0.0.0'
                    
                    self.data_socket = socket.socket(addr_family, socket.SOCK_STREAM)
                    self.data_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                    self.data_socket.bind((bind_addr, 0))
                    self.data_socket.listen(1)
                    
                    port = self.data_socket.getsockname()[1]
                    print(f"EPSV mode - waiting for connection on port {port}")
                    
                    # EPSV response format: 229 Entering Extended Passive Mode (|||port|)
                    self.send_response(client_socket, 229, f"Entering Extended Passive Mode (|||{port}|)")
                elif command == 'CWD':
                    path = args
                    try:
                        if os.path.isdir(path):
                            os.chdir(path)
                            self.current_path = os.getcwd()
                            self.send_response(client_socket, 250, f"Directory changed to {path}")
                        else:
                            self.send_response(client_socket, 550, f"Directory not found: {path}")
                    except Exception as e:
                        self.send_response(client_socket, 550, f"Failed to change directory: {str(e)}")
                elif command == 'LIST' or command == 'NLST':
                    if self.data_socket:
                        self.send_response(client_socket, 150, "Opening data connection for directory listing")
                        try:
                            data_conn, addr = self.data_socket.accept()
                            print(f"Data connection established from {addr}")
                            
                            files = os.listdir(self.current_path)
                            listing = []
                            
                            for filename in files:
                                path = os.path.join(self.current_path, filename)
                                stats = os.stat(path)
                                
                                # create a formatted directory listing
                                file_type = 'd' if os.path.isdir(path) else '-'
                                size = stats.st_size
                                
                                if command == 'LIST':
                                    # full listing
                                    permissions = 'rwxrwxrwx'
                                    entry = f"{file_type}{permissions} 1 owner group {size} Jan 1 00:00 {filename}"
                                    listing.append(entry)
                                else:
                                    # just names
                                    listing.append(filename)
                            
                            listing_str = '\r\n'.join(listing) + '\r\n'
                            data_conn.send(listing_str.encode())
                            data_conn.close()
                            self.send_response(client_socket, 226, "Directory listing complete")
                        except Exception as e:
                            self.send_response(client_socket, 425, f"Error during listing: {str(e)}")
                        finally:
                            self.data_socket.close()
                            self.data_socket = None
                    else:
                        self.send_response(client_socket, 425, "Use PASV or EPSV first")
                elif command == 'RETR':
                    if not args:
                        self.send_response(client_socket, 501, "Missing filename parameter")
                        continue
                        
                    filename = args
                    filepath = os.path.join(self.current_path, filename)
                    
                    if not os.path.exists(filepath):
                        self.send_response(client_socket, 550, f"File not found: {filename}")
                        continue
                        
                    if self.data_socket:
                        self.send_response(client_socket, 150, f"Opening data connection for {filename}")
                        try:
                            data_conn, addr = self.data_socket.accept()
                            print(f"Data connection established from {addr}")
                            
                            # read and send file in binary mode
                            with open(filepath, 'rb') as file:
                                while True:
                                    data = file.read(8192)
                                    if not data:
                                        break
                                    data_conn.send(data)
                            
                            data_conn.close()
                            self.send_response(client_socket, 226, "Transfer complete")
                        except Exception as e:
                            self.send_response(client_socket, 426, f"Transfer failed: {str(e)}")
                        finally:
                            self.data_socket.close()
                            self.data_socket = None
                    else:
                        self.send_response(client_socket, 425, "Use PASV or EPSV first")
                elif command == 'STOR':
                    if not args:
                        self.send_response(client_socket, 501, "Missing filename parameter")
                        continue
                        
                    filename = args
                    filepath = os.path.join(self.current_path, filename)
                    
                    if self.data_socket:
                        self.send_response(client_socket, 150, f"Opening data connection for {filename}")
                        try:
                            data_conn, addr = self.data_socket.accept()
                            print(f"Data connection established from {addr}")
                            
                            # receive and save file data
                            with open(filepath, 'wb') as file:
                                while True:
                                    data = data_conn.recv(8192)
                                    if not data:
                                        break
                                    file.write(data)
                            
                            data_conn.close()
                            self.send_response(client_socket, 226, "Transfer complete")
                        except Exception as e:
                            self.send_response(client_socket, 426, f"Transfer failed: {str(e)}")
                        finally:
                            self.data_socket.close()
                            self.data_socket = None
                    else:
                        self.send_response(client_socket, 425, "Use PASV or EPSV first")
                elif command == 'NOOP':
                    self.send_response(client_socket, 200, "NOOP command successful")
                elif command == 'QUIT':
                    self.send_response(client_socket, 221, "Goodbye")
                    break
                elif command == 'DELE':
                    if not args:
                        self.send_response(client_socket, 501, "Missing filename parameter")
                        continue
                        
                    filename = args
                    filepath = os.path.join(self.current_path, filename)
                    
                    if not os.path.exists(filepath):
                        self.send_response(client_socket, 550, f"File not found: {filename}")
                        continue
                        
                    try:
                        os.remove(filepath)
                        self.send_response(client_socket, 250, f"File {filename} deleted")
                    except Exception as e:
                        self.send_response(client_socket, 550, f"Failed to delete file: {str(e)}")
                        
                elif command == 'ZIP':
                    if not args:
                        self.send_response(client_socket, 501, "Missing directory parameter")
                        continue
                        
                    dirname = args
                    dirpath = os.path.join(self.current_path, dirname)
                    
                    if not os.path.exists(dirpath) or not os.path.isdir(dirpath):
                        self.send_response(client_socket, 550, f"Directory not found: {dirname}")
                        continue
                        
                    try:
                        import zipfile
                        import time
                        
                        # create zip filename based on directory name and timestamp
                        zip_filename = f"{dirname}_{int(time.time())}.zip"
                        zip_filepath = os.path.join(self.current_path, zip_filename)
                        
                        # create a new zip file
                        with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                            # walk through all files in the directory
                            for root, _, files in os.walk(dirpath):
                                for file in files:
                                    filepath = os.path.join(root, file)
                                    # calculate path within the zip file (relative to the directory)
                                    arcname = os.path.relpath(filepath, dirpath)
                                    zipf.write(filepath, arcname)
                        
                        self.send_response(client_socket, 200, f"Directory {dirname} zipped to {zip_filename}")
                    except Exception as e:
                        self.send_response(client_socket, 550, f"Failed to zip directory: {str(e)}")
                else:
                    self.send_response(client_socket, 502, "Command not implemented")
            
            except Exception as e:
                print(f"Error handling client: {e}")
                break
        
        print("Client disconnected")
        client_socket.close()
        if self.data_socket:
            self.data_socket.close()

if __name__ == "__main__":
    server = FTPServer()
    try:
        server.start()
    except KeyboardInterrupt:
        server.running = False
        server.server_socket.close()
        print("Server stopped")