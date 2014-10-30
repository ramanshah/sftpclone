"""SFTPSync tests."""

#! /usr/bin/env python3
# coding = utf-8
# author = Adriano Di Luzio

# Simply launch me by using nosetests and I'll do the magic.
# I require paramiko

import threading
import os
from os.path import join
from shutil import rmtree, copy
import random
from stat import S_ISDIR

import paramiko
from t.stub_sftp import StubServer, StubSFTPServer
from t.utils import t_path, list_files
import socket
import select

from nose import with_setup

from sftpclone import SFTPClone


REMOTE_ROOT = t_path("server_root")
REMOTE_FOLDER = "server_folder"
REMOTE_PATH = join(REMOTE_ROOT, REMOTE_FOLDER)

LOCAL_FOLDER = t_path("local_folder")

event = threading.Event()


def _start_sftp_server():
    """Start the SFTP local server."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setblocking(0)
    sock.bind(('localhost', 2222))
    sock.listen(10)

    reads = {sock}
    others = set()

    while not event.is_set():
        ready_to_read, _, _ = \
            select.select(
                reads,
                others,
                others,
                1)

        if sock in ready_to_read:
            client_socket, address = sock.accept()
            ts = paramiko.Transport(client_socket)

            host_key = paramiko.RSAKey.from_private_key_file(
                t_path('server_id_rsa')
            )
            ts.add_server_key(host_key)
            server = StubServer()
            ts.set_subsystem_handler(
                'sftp', paramiko.SFTPServer, StubSFTPServer)
            ts.start_server(server=server)


def setup_module():
    """Setup in a new thread the SFTP local server."""
    t = threading.Thread(target=_start_sftp_server, name="server")
    t.start()


def teardown_module():
    """Stop the SFTP server by setting its event.

    Clean remaining directories (in case of failures).
    """
    event.set()

    rmtree(REMOTE_PATH, ignore_errors=True)
    rmtree(LOCAL_FOLDER, ignore_errors=True)


def setup_test():
    """Create the needed directories."""
    os.mkdir(REMOTE_PATH)
    os.mkdir(LOCAL_FOLDER)
setup_test.__test__ = False


def teardown_test():
    """Clean the created directories."""
    list_files(LOCAL_FOLDER)
    list_files(REMOTE_PATH)

    rmtree(REMOTE_PATH, ignore_errors=True)
    rmtree(LOCAL_FOLDER, ignore_errors=True)
teardown_test.__test__ = False


def _sync():
    """Launch sync."""
    sync = SFTPClone(
        LOCAL_FOLDER,
        'test@127.0.0.1:' + '/' + REMOTE_FOLDER,
        key=t_path('id_rsa'),
        port=2222
    )
    sync.run()
_sync.__test__ = False


@with_setup(setup_test, teardown_test)
def test_directory_upload():
    """Test upload/creation of whole directory trees."""
    # add some dirs to both the local/remote directories
    local_dirs = {str(f) for f in range(8)}
    remote_dirs = set(random.sample(local_dirs, 3))

    spurious_dir = join(REMOTE_PATH, random.choice(tuple(local_dirs - remote_dirs)))
    os.open(spurious_dir, os.O_CREAT)

    for f in local_dirs:
        os.mkdir(join(LOCAL_FOLDER, f))
    for f in remote_dirs:
        os.mkdir(join(REMOTE_PATH, f))

    full_dirs = set(random.sample(local_dirs, 2))
    for f in full_dirs:
        for i in range(random.randint(1, 10)):
            os.open(join(LOCAL_FOLDER, f, str(i)), os.O_CREAT)

    _sync()

    assert S_ISDIR(os.stat(spurious_dir).st_mode)
    for d in full_dirs:
        assert os.listdir(join(LOCAL_FOLDER, d)) == os.listdir(join(REMOTE_PATH, d))


@with_setup(setup_test, teardown_test)
def test_file_upload():
    """
    Test upload/creation of files.

    Upload files present in the local directory but not in the remote one.
    """
    # add some file to both the local/remote directories
    local_files = {str(f) for f in range(5)}
    remote_files = set(random.sample(local_files, 3))

    for f in local_files:
        os.open(join(LOCAL_FOLDER, f), os.O_CREAT)
    for f in remote_files:
        os.open(join(REMOTE_PATH, f), os.O_CREAT)

    local_files |= {"5"}
    with open(join(LOCAL_FOLDER, "5"), 'w') as f:
        print("This is the local file.", file=f, flush=True)
    remote_files |= {"5"}
    with open(join(REMOTE_PATH, "5"), 'w') as f:
        print("This is the remote file.", file=f, flush=True)

    local_files |= {"6"}
    l = join(LOCAL_FOLDER, "6")
    with open(l, 'w') as f:
        print("This is another file.", file=f, flush=True)
    remote_files |= {"6"}
    copy(l, join(REMOTE_PATH, "6"))

    # Sync and check that missing files where uploaded
    _sync()

    assert set(os.listdir(REMOTE_PATH)) == local_files
    files = {"5", "6"}
    for f in files:
        lf, rf = join(LOCAL_FOLDER, f), join(REMOTE_PATH, f)
        assert os.stat(lf).st_size == os.stat(rf).st_size
        assert os.stat(lf).st_mtime == os.stat(rf).st_mtime
        assert os.stat(lf).st_mode == os.stat(rf).st_mode

        with open(lf, 'r') as f_one:
            with open(rf, 'r') as f_two:
                assert f_one.read() == f_two.read()


@with_setup(setup_test, teardown_test)
def test_remote_but_not_local_files():
    """
    Test deletion of files (when needed).

    Remove files present on the remote directory but not in the local one.
    """
    # add some file to the remote directory
    remote_files = {str(f) for f in range(5)}
    local_files = set(random.sample(remote_files, 3))

    for f in remote_files:
        os.open(join(REMOTE_PATH, f), os.O_CREAT)
    for f in local_files:
        os.open(join(LOCAL_FOLDER, f), os.O_CREAT)

    # Sync and check the results
    _sync()
    assert set(os.listdir(REMOTE_PATH)) == local_files


@with_setup(setup_test, teardown_test)
def test_remote_but_not_local_directories():
    """
    Test deletion of directories (when needed).

    Remove directories present on the remote directory but not in the local one.
    """
    # add some directories to the remote directory
    remote_dirs = {str(f) for f in range(6)}
    local_dirs = set(random.sample(remote_dirs, 4))

    for f in remote_dirs:
        os.mkdir(join(REMOTE_PATH, f))
    for f in local_dirs:
        os.mkdir(join(LOCAL_FOLDER, f))

    # now we create some remote directories that should be deleted
    full_dirs = set(random.sample(local_dirs, 2))
    for f in full_dirs:
        inner_path = join(REMOTE_PATH, f)
        for s in range(random.randint(1, 4)):
            inner_path = join(inner_path, str(s))
            os.mkdir(inner_path)

        for i in range(3):
            os.open(join(inner_path, str(i)), os.O_CREAT)

    list_files(REMOTE_PATH)

    # Sync and check the results
    _sync()

    assert set(os.listdir(REMOTE_PATH)) == local_dirs
    for f in full_dirs:
        assert os.listdir(join(REMOTE_PATH, f)) == os.listdir(
            join(LOCAL_FOLDER, f))
