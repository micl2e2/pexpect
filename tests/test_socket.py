#!/usr/bin/env python
'''
PEXPECT LICENSE

    This license is approved by the OSI and FSF as GPL-compatible.
        http://opensource.org/licenses/isc-license.txt

    Copyright (c) 2012, Noah Spurrier <noah@noah.org>
    PERMISSION TO USE, COPY, MODIFY, AND/OR DISTRIBUTE THIS SOFTWARE FOR ANY
    PURPOSE WITH OR WITHOUT FEE IS HEREBY GRANTED, PROVIDED THAT THE ABOVE
    COPYRIGHT NOTICE AND THIS PERMISSION NOTICE APPEAR IN ALL COPIES.
    THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
    WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
    MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
    ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
    WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
    ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
    OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.

'''
import pexpect
from pexpect import socket_pexpect
import unittest
from . import PexpectTestCase
import multiprocessing
import os
import signal
import socket
import time
import errno

# Python 3.14 changed the non-macOS POSIX default to forkserver
# but the code in this module does not work with it
# See https://github.com/python/cpython/issues/125714
if multiprocessing.get_start_method() == 'forkserver':
    mp_context = multiprocessing.get_context(method='fork')
else:
    mp_context = multiprocessing.get_context()


class SocketServerError(Exception):
    pass


class ExpectTestCase(PexpectTestCase.PexpectTestCase):

    def setUp(self):
        print(self.id())
        PexpectTestCase.PexpectTestCase.setUp(self)
        self.af = socket.AF_INET
        self.host = '127.0.0.1'
        try:
            socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        except socket.error:
            try:
                socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
                self.af = socket.AF_INET6
                self.host = '::1'
            except socket.error:
                pass
        self.port = 49152 + 10000
        self.motd = b"""\
------------------------------------------------------------------------------
*                  Welcome to the SOCKET UNIT TEST code!                     *
------------------------------------------------------------------------------
*                                                                            *
* This unit test code is our best effort at testing the ability of the       *
* pexpect library to handle sockets. We need some text to test buffer size   *
* handling.                                                                  *
*                                                                            *
* A page is 1024 bytes or 1K. 80 x 24 = 1920. So a standard terminal window  *
* contains more than one page. We actually want more than a page for our     *
* tests.                                                                     *
*                                                                            *
* This is the twelfth line, and we need 24. So we need a few more paragraphs.*
* We can keep them short and just put lines between them.                    *
*                                                                            *
* The 80 x 24 terminal size comes from the ancient past when computers were  *
* only able to display text in cuneiform writing.                            *
*                                                                            *
* The cunieform writing system used the edge of a reed to make marks on clay *
* tablets.                                                                   *
*                                                                            *
* It was the forerunner of the style of handwriting used by doctors to write *
* prescriptions. Thus the name: pre (before) script (writing) ion (charged   *
* particle).                                                                 *
------------------------------------------------------------------------------
""".replace(b'\n', b'\n\r') + b"\r\n"
        self.prompt1 = b'Press Return to continue:'
        self.prompt2 = b'Rate this unit test>'
        self.prompt3 = b'Press X to exit:'
        self.enter = b'\r\n'
        self.exit = b'X\r\n'
        self.server_up = mp_context.Event()
        self.server_process = mp_context.Process(target=self.socket_server, args=(self.server_up,))
        self.server_process.daemon = True
        self.server_process.start()
        counter = 0
        while not self.server_up.is_set():
            time.sleep(0.250)
            counter += 1
            if counter > (10 / 0.250):
                raise SocketServerError("Could not start socket server")

    def tearDown(self):
        os.kill(self.server_process.pid, signal.SIGINT)
        self.server_process.join(timeout=5.0)
        PexpectTestCase.PexpectTestCase.tearDown(self)

    def socket_server(self, server_up):
        sock = None
        try:
            sock = socket.socket(self.af, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((self.host, self.port))
            sock.listen(5)
            server_up.set()
            while True:
                (conn, addr) = sock.accept()
                conn.send(self.motd)
                conn.send(self.prompt1)
                result = conn.recv(1024)
                if result != self.enter:
                    break
                conn.send(self.prompt2)
                result = conn.recv(1024)
                if result != self.enter:
                    break
                conn.send(self.prompt3)
                result = conn.recv(1024)
                if result.startswith(self.exit[0]):
                    conn.shutdown(socket.SHUT_RDWR)
                    conn.close()
        except KeyboardInterrupt:
            pass
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
                sock.close()
            except socket.error:
                pass
        exit(0)

    def spawn(self, socket, timeout=30, use_poll=False):
        """override me with other ways of spawning on a socket"""
        return socket_pexpect.SocketSpawn(socket, timeout=timeout, use_poll=use_poll)

    def socket_fn(self, timed_out, all_read):
        result = 0
        try:
            sock = socket.socket(self.af, socket.SOCK_STREAM)
            sock.connect((self.host, self.port))
            session = self.spawn(sock, timeout=10)
            # Get all data from server
            session.read_nonblocking(size=4096)
            all_read.set()
            # This read should timeout
            session.read_nonblocking(size=4096)
        except pexpect.TIMEOUT:
            timed_out.set()
            result = errno.ETIMEDOUT
        exit(result)

    def test_socket(self):
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        session.expect(self.prompt1)
        self.assertEqual(session.before, self.motd)
        session.send(self.enter)
        session.expect(self.prompt2)
        session.send(self.enter)
        session.expect(self.prompt3)
        session.send(self.exit)
        session.expect(pexpect.EOF)
        self.assertEqual(session.before, b'')

    def test_socket_with_write(self):
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        session.expect(self.prompt1)
        self.assertEqual(session.before, self.motd)
        session.write(self.enter)
        session.expect(self.prompt2)
        session.write(self.enter)
        session.expect(self.prompt3)
        session.write(self.exit)
        session.expect(pexpect.EOF)
        self.assertEqual(session.before, b'')

    def test_timeout(self):
        with self.assertRaises(pexpect.TIMEOUT):
            sock = socket.socket(self.af, socket.SOCK_STREAM)
            sock.connect((self.host, self.port))
            session = self.spawn(sock, timeout=10)
            session.expect(b'Bogus response')

    def test_interrupt(self):
        timed_out = mp_context.Event()
        all_read = mp_context.Event()
        test_proc = mp_context.Process(target=self.socket_fn, args=(timed_out, all_read))
        test_proc.daemon = True
        test_proc.start()
        while not all_read.is_set():
            time.sleep(1.0)
        os.kill(test_proc.pid, signal.SIGWINCH)
        while not timed_out.is_set():
            time.sleep(1.0)
        test_proc.join(timeout=5.0)
        self.assertEqual(test_proc.exitcode, errno.ETIMEDOUT)

    def test_multiple_interrupts(self):
        timed_out = mp_context.Event()
        all_read = mp_context.Event()
        test_proc = mp_context.Process(target=self.socket_fn, args=(timed_out, all_read))
        test_proc.daemon = True
        test_proc.start()
        while not all_read.is_set():
            time.sleep(1.0)
        while not timed_out.is_set():
            os.kill(test_proc.pid, signal.SIGWINCH)
            time.sleep(1.0)
        test_proc.join(timeout=5.0)
        self.assertEqual(test_proc.exitcode, errno.ETIMEDOUT)

    def test_maxread(self):
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        session.maxread = 1100
        session.expect(self.prompt1)
        self.assertEqual(session.before, self.motd)
        session.send(self.enter)
        session.expect(self.prompt2)
        session.send(self.enter)
        session.expect(self.prompt3)
        session.send(self.exit)
        session.expect(pexpect.EOF)
        self.assertEqual(session.before, b'')

    def test_fd_isalive(self):
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        assert session.isalive()
        sock.close()
        assert not session.isalive(), "Should not be alive after close()"

    def test_fd_isalive_poll(self):
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10, use_poll=True)
        assert session.isalive()
        sock.close()
        assert not session.isalive(), "Should not be alive after close()"

    def test_fd_isatty(self):
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10)
        assert not session.isatty()
        session.close()

    def test_fd_isatty_poll(self):
        sock = socket.socket(self.af, socket.SOCK_STREAM)
        sock.connect((self.host, self.port))
        session = self.spawn(sock, timeout=10, use_poll=True)
        assert not session.isatty()
        session.close()


if __name__ == '__main__':
    unittest.main()

suite = unittest.TestLoader().loadTestsFromTestCase(ExpectTestCase)
