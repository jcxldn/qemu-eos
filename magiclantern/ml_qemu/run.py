#!/usr/bin/env python3

import os
import argparse
import subprocess
from time import sleep
import socket

import vncdotool
from vncdotool import api

class QemuRunnerError(Exception):
    pass


class QemuRunner:
    """
    Context manager for running Qemu, this allows automatically
    cleaning up Qemu monitor socket via "with".  Entering the
    context starts Qemu, via Popen therefore non-blocking.

    You can control Qemu within the context, either via Qemu monitor,
    or VNC api.

    Leaving the context ends Qemu and cleans up (principally the
    monitor socket).

    If you fall out of the context, Qemu will be ended by terminating
    the process.  This is not generally what you want.  If you
    do something like: 'with QemuRunner() as q', then you can do
    q.qemu_process.wait() and it will block until the user ends Qemu.
    You can attempt a graceful power down of the VM via q.shutdown(),
    or tell Qemu to force a power down via q.shutdown(force=True)
    """
    def __init__(self, build_dir, rom_dir, cam,
                 monitor_socket_path="",
                 vnc_display="",
                 boot=False):
        # TODO:
        # handle QEMU_EOS_DEBUGMSG,
        # allow selecting drive images,
        # ensure Qemu test suite works in the same way with this vs run_canon_fw.sh,
        # handle passing other args, e.g. -d romcpy
        # improve boot / non-boot selection (currently, -M CAM,firmware=boot=0, a better way
        #   would be creating a proper qemu option group)
        # check for arm-softmmu subdir and fail gracefully if missing,
        # check for disk_images subdir, fail gracefully,
        # check for model specific rom subdir, fail gracefully
        self.rom_dir = rom_dir
        # FIXME make this a class property, can't remember syntax right now
        self.screen_cap_prefix = "test_"
        self.screen_cap_counter = 0
        if monitor_socket_path:
            self.monitor_socket_path = monitor_socket_path
        else:
            self.monitor_socket_path = "qemu.monitor"

        if boot:
            model = cam + ",firmware=boot=1"
        else:
            model = cam + ",firmware=boot=0"

        self.qemu_command = [os.path.join(build_dir, "arm-softmmu", "qemu-system-arm"),
                             "-drive", "if=sd,format=raw,file=" +
                                     os.path.join(build_dir, "disk_images", "sd.img"),
                             "-drive", "if=ide,format=raw,file=" +
                                     os.path.join(build_dir, "disk_images", "cf.img"),
                             "-chardev", "socket,server,nowait,path=" + self.monitor_socket_path + ",id=monsock",
                             "-mon", "chardev=monsock,mode=readline",
                             "-name", cam,
                             "-M", model,
                            ]

        self.vnc_display = vnc_display
        if vnc_display:
            self.qemu_command.extend(["-vnc", vnc_display])
            self.vnc_client = vncdotool.api.connect(self.vnc_display)
        else:
            self.vnc_client = None

    def __enter__(self):
        qemu_env = os.environ
        # FIXME remove QEMU_EOS_WORKDIR and make it a proper qemu CLI option
        # TODO check if this class works outside of use as a context
        # manager, I suspect it doesn't.  Fix as appropriate, or make
        # failure explicit outside that usage?
        qemu_env["QEMU_EOS_WORKDIR"] = self.rom_dir
        print(self.qemu_command)
        self.qemu_process = subprocess.Popen(self.qemu_command,
                                             env=qemu_env,
                                             stdin=subprocess.PIPE,
                                             stdout=subprocess.PIPE)
        # TODO: bit hackish, but we give some time for Qemu
        # to start.  This prevents problems with VNC access
        # happening before Qemu is up.  There should be a more
        # graceful way.  Check status via monitor socket possibly?
        sleep(1.5)
        return self

    def __exit__(self, *args):
        self.qemu_process.terminate()
        try:
            os.remove(self.monitor_socket_path)
        except FileNotFoundError:
            pass

    def shutdown(self, force=False):
        """
        Instructs Qemu to shut down the VM, via monitor socket.
        """
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.connect(self.monitor_socket_path)
        if force:
            s.send(b"quit\n")
        else:
            s.send(b"system_powerdown\n")
        sleep(2)

    def key_press(self, key, capture_screen=True):
        """
        Use VNC to press a key in the VM, and by default,
        capture the screen a short time afterwards.
        """
        self.vnc_client.keyPress(key)
        if capture_screen:
            self.capture_screen()

    def capture_screen(self):
        """
        Capture VM screen via VNC.
        """
        sleep(0.1)
        n = self.screen_cap_counter
        self.screen_cap_counter += 1
        self.vnc_client.captureScreen(self.screen_cap_prefix
                                      + str(n).zfill(2)
                                      + ".png")
        sleep(0.1)
