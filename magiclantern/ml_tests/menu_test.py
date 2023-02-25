#!/usr/bin/env python3

import os
import hashlib

from . import test
from . import locking_print
from ml_qemu.run import QemuRunner


class MenuTest(test.Test):
    """
    This test steps through Canon menus in Qemu,
    ensuring they look how we expect,
    and tries to cleanly shutdown the cam.

    ML is not active.
    """
    # Canon saves state of all menus into ROM,
    # including cursor position etc.  Thus it is simplest if we
    # treat each rom as needing a unique sequence for this test.
    # Here we only want to check if we can reach the expected menus.
    #
    # If you have a new ROM, you'll need to determine a new sequence
    # (if you're lucky, an existing rom will be close and can be
    # adapted).

    qemu_key_sequences = {
                "e6a90e8497c2c1187e0322010a42b9b5": # 5D3 ROM1
                ["m", "l", "l", "m",
                 "left", "left", "left", "left", "left", "left", "left", "left", "left",
                 "left", "left", "left", "left", "left", "left", "left", "left", "left",
                 "left", "left", "left", # cycle through all menus
                 "up", "up", "space", "down", "space", # sub-menu test, Tv/Av dial direction
                 "right", "right", "right", "up", "space", "pgdn", "space", # ISO speed increment, wheel test
                ],
                "424545a5cfe10b1a5d8cefffe9fe5297": # 50D ROM1
                ["m", "l", "l", "m", "right", "right", "right", "right",
                 "right", "right", "right", "right", "right", # cycle through all menus
                 "up", "up", "space", "down", "space", # check sub-menus work, turn beep off
                 "right", "up", "up", "space", "pgdn", "space", # check wheel controls using Expo Comp sub-menu
                ],
                "d266ce304585952fb3a05a9f6c304f2f": # 60D ROM1
                ["m", "l", "l", "m", "left", "left", "left", "left",
                 "left", "left", "left", "left", "left", "left", "left", # cycle through all menus
                 "up", "up", "space", "down", "space", # check sub-menus work; change auto rotation
                 "left", "up", "up", "space", "pgup", "space", # check wheel controls on Play options
                ],
                "e06a0e3919ac4d4ef609a864e937a5d3": # 100D ROM1
                ["m", "wait l", "wait l", "m", # LV looks weird on this cam and takes a long time to activate
                 "right", "right", "right", "right",
                 "right", "right", "right", "right", "right", "right",
                 "right", # cycle through all menus
                 "up", "up", "up", "space", "down", "space", # check sub-menus; LCD auto off
                ],
                "f6c20df071b3514fa65f35dc5d71b484": # 700D ROM1
                ["f1", "m", "right", "right", "right", "right", "right",
                 "right", "right", "right", "right", "right", "right",
                 "right", # cycle through all menus.  This rom has no lens attached and LV usage seems to lock the cam.
                 "space", "right", "space", # check sub-menus, change movie res
                 # no wheel controls on this cam?  PgUp / PgDown are unmapped.
                 "left", "space", "down", "down", "up", "space", # test up/down in grid display sub-menu
                ],
                "0a9fce1e4ef6d2ac2c3bc63eb96d3c34": # 500D ROM1
                ["f1", "m", "l", "l", "m", # inital info screen, menu and LV
                 "left", "left", "left", "left", "left", "left", "left", "left", # cycle through menus
                 "right", "space", "right", "space", # sub-menu test, change screen brightness
                 "right", "space", "up", "up", "down", "space", # up/down test.  Unsure on sub-menu, it's Polish lang
                ],
                }

    def run(self, lock):
        self.lock = lock
        if self.verbose:
            locking_print("MenuTest starting on %s %s" %
                  (self.cam.model, self.cam.code_rom_md5),
                  lock)

        if self.cam.model not in self.known_cams:
            return self.return_failure("No tests known for cam: %s"
                                       % self.cam.model)

        if self.cam.code_rom_md5 not in self.known_cams[self.cam.model]:
            return self.return_failure("Unknown rom for cam, MD5 sum: %s"
                                       % self.cam.code_rom_md5)

        if self.cam.code_rom_md5 not in self.qemu_key_sequences:
            return self.return_failure("Unknown rom for MenuTest, MD5 sum: %s"
                                       % self.cam.code_rom_md5)

        key_sequence = self.qemu_key_sequences[self.cam.code_rom_md5]


        # invoke qemu and control it to run the test
        with QemuRunner(self.qemu_dir, self.cam.rom_dir, self.cam.source_dir,
                        self.cam.model,
                        unreliable_screencaps=self.cam.unreliable_screencaps,
                        sd_file=self.sd_file, cf_file=self.cf_file,
                        stdout=os.path.join(self.output_dir, "qemu.stdout"),
                        stderr=os.path.join(self.output_dir, "qemu.stderr"),
                        monitor_socket_path=self.qemu_monitor_path,
                        vnc_display=self.vnc_display,
                        verbose=self.verbose) as self.qemu_runner:
            q = self.qemu_runner

            # Let's try some filthy hacking.  For unknown reasons,
            # framebufferUpdateRequest(incremental=1), called internally as
            # part of expectScreen(), causes the screen compare to always fail.
            # That param is not exposed as part of expectScreen().
            # Monkey patch the function with a wrapper that forces incremental=0.
            #
            # Getting to the actual function is its own special joy, it
            # is quite indirect.
            def _fbReplacer(obj, x=0, y=0, width=None, height=None, incremental=0):
                # the following will get called as a method, therefore passing self implicitly
                obj._framebufferUpdateRequest(x=x, y=y, width=width, height=height, incremental=0)

            parent = q.vnc_client.factory.protocol
            parent._framebufferUpdateRequest = parent.framebufferUpdateRequest
            parent.framebufferUpdateRequest = _fbReplacer

            q.screen_cap_prefix = "menu_test_"
            for k in key_sequence:
                delay = 0.3
                if k.startswith("wait"):
                    # prefixing a vnc key string with "wait " adds
                    # extra delay before capturing the screen.  Some
                    # menu transitions are much slower than others
                    delay = 5
                    k = k.split()[-1]
                q.key_press(k, delay=delay)
                expected_output_path = os.path.join(self.expected_output_dir,
                                                    q.screen_cap_name)
                try:
                    q.vnc_client.expectScreen(expected_output_path, maxrms=0.0)
                except FileNotFoundError:
                    if self.force_continue:
                        pass
                    else:
                        return self.return_failure("Missing expected output file: %s"
                                                   % expected_output_path)
                except TimeoutError:
                    # vncdotool api object can throw this if its timeout property is set,
                    # we do this in QemuRunner.
                    #
                    # This means we never saw the right screen, the best we can do to help
                    # debug is save the last known content.
                    fail_name = "fail_" + q.screen_cap_name
                    q.vnc_client.screen.save(fail_name)
                    if self.force_continue:
                        pass
                    else:
                        return self.return_failure("Qemu screen never matched against "
                                                   "expected result file '%s'\n, check '%s'"
                                                   % (expected_output_path, fail_name))

            # attempt clean shutdown via Qemu monitor socket
            q.shutdown()
        #locking_print(f"PASS: {self.__class__.__name__}, {self.cam.model}", lock)
        return self.return_success()

