import socket
import os

HOST = '127.0.0.1'
PORT = 20000
CLIENT_DIR = os.path.join(os.getcwd(), 'storage')

def recv_full_response(sock):
    data = b''
    while True:
        part = sock.recv(4096)
        data += part
        if len(part) < 4096:
            break
    return data.decode()

def enter_passive_mode(response):
    start = response.find('(')
    end = response.find(')')
    if start == -1 or end == -1:
        return None, None
    parts = response[start+1:end].split(',')
    ip = '.'.join(parts[:4])
    port = int(parts[4]) * 256 + int(parts[5])
    return ip, port

def open_data_connection(control_socket):
    control_socket.sendall("PASV\r\n".encode())
    pasv_resp = control_socket.recv(1024).decode()
    print(pasv_resp.strip())
    ip, port = enter_passive_mode(pasv_resp)
    if ip is None:
        print("Failed to enter passive mode.")
        return None
    data_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    data_socket.connect((ip, port))
    return data_socket

# Connect to server
control_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
control_socket.connect((HOST, PORT))
print(control_socket.recv(1024).decode())  # Server greeting

# Authenticate
username = input("Username: ")
control_socket.sendall(f"USER {username}\r\n".encode())
print(control_socket.recv(1024).decode())

password = input("Password: ")
control_socket.sendall(f"PASS {password}\r\n".encode())
print(control_socket.recv(1024).decode())

# Main loop
while True:
    command = input("ftp> ")
    if command.upper() == "QUIT":
        control_socket.sendall("QUIT\r\n".encode())
        print(control_socket.recv(1024).decode())
        break

    cmd = command.strip().split()
    base_cmd = cmd[0].upper()

    # LIST
    if base_cmd == "LIST":
        data_socket = open_data_connection(control_socket)
        if data_socket:
            control_socket.sendall("LIST\r\n".encode())
            print(control_socket.recv(1024).decode())  # 150
            print(recv_full_response(data_socket))
            print(control_socket.recv(1024).decode())  # 226
            data_socket.close()

    # RETR (download)
    elif base_cmd == "RETR" and len(cmd) > 1:
        filename = cmd[1]
        data_socket = open_data_connection(control_socket)
        if data_socket:
            control_socket.sendall(f"RETR {filename}\r\n".encode())
            resp = control_socket.recv(1024).decode()
            print(resp.strip())
            if resp.startswith("150"):
                file_path = os.path.join(CLIENT_DIR, filename)  # Save file to the client folder
                with open(file_path, 'wb') as f:
                    while True:
                        chunk = data_socket.recv(1024)
                        if not chunk:
                            break
                        f.write(chunk)
                data_socket.close()
                print(control_socket.recv(1024).decode())  # 226

    # STOR (upload)
    elif base_cmd == "STOR" and len(cmd) > 1:
        filename = cmd[1]
        file_path = os.path.join(CLIENT_DIR, filename)
        
        if not os.path.exists(file_path):
            print("File does not exist.")
            continue

        data_socket = open_data_connection(control_socket)
        if data_socket:
            control_socket.sendall(f"STOR {filename}\r\n".encode())
            resp = control_socket.recv(1024).decode()
            print(resp.strip())
            if resp.startswith("150"):
                with open(file_path, 'rb') as f:
                    data_socket.sendfile(f)
                data_socket.close()
                print(control_socket.recv(1024).decode())  # 226

    # Basic Commands (PWD, CWD, SYST, HELP, NOOP)
    else:
        control_socket.sendall(f"{command}\r\n".encode())
        print(control_socket.recv(1024).decode())

control_socket.close()