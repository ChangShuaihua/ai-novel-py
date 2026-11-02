import socket
import threading
import time

ports = [443, 8000, 8080, 8443, 8888, 3000, 9000, 8081]


def serve(port):
    sock = socket.socket()
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("0.0.0.0", port))
    except OSError as exc:
        print(f"bind-fail {port} {exc}", flush=True)
        return
    sock.listen(5)
    print(f"listen {port}", flush=True)
    sock.settimeout(20)
    try:
        while True:
            client, _addr = sock.accept()
            client.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK")
            client.close()
    except Exception:
        pass
    sock.close()


for port in ports:
    threading.Thread(target=serve, args=(port,), daemon=True).start()
time.sleep(18)
