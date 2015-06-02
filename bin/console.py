"""
fault.io interactive console
"""
from .. import console

name = 'console'
initialize = console.initialize

if __name__ == '__main__':
	from .. import library as iolib
	iolib.execute(console = (console.initialize,))
