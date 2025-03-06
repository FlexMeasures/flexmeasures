from simple_websocket import Client, ConnectionClosed

def main():
    ws = Client.connect('ws://0.0.0.0:5000/ping2')
    try:
        while True:
            data = input('> ')
            ws.send(data)
            data = ws.receive()
            print(f'< {data}')
    except (KeyboardInterrupt, EOFError, ConnectionClosed):
        ws.close()

if __name__ == '__main__':
    main()