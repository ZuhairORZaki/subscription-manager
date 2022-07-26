# Copyright (c) 2012 Red Hat, Inc.
#
# This software is licensed to you under the GNU General Public License,
# version 2 (GPLv2). There is NO WARRANTY for this software, express or
# implied, including the implied warranties of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. You should have received a copy of GPLv2
# along with this software; if not, see
# http://www.gnu.org/licenses/old-licenses/gpl-2.0.txt.
#
# Red Hat trademarks are not licensed under GPLv2. No permission is
# granted to use or replicate Red Hat trademarks that are incorporated
# in this software or its documentation.
#

import functools
import os
import re
import sys
import time
import threading
from typing import Callable, List, Optional

import urllib.parse

import rhsm.config
from rhsm.config import DEFAULT_PROXY_PORT


PROGRESS_MESSAGES: bool = True
"""Enable or disable progress messages.

Please note that they can be also disabled via rhsm.conf file or with
environment variable (when debugging is turned on), this variable (working as
module singleton) is used for turning it off dynamically via CLI option.
"""


def remove_scheme(uri):
    """Remove the scheme component from a URI."""
    return re.sub("^[A-Za-z][A-Za-z0-9+-.]*://", "", uri)


class ServerUrlParseError(Exception):
    def __init__(self, serverurl, msg=None):
        self.serverurl = serverurl
        self.msg = msg


class ServerUrlParseErrorEmpty(ServerUrlParseError):
    pass


class ServerUrlParseErrorNone(ServerUrlParseError):
    pass


class ServerUrlParseErrorPort(ServerUrlParseError):
    pass


class ServerUrlParseErrorPath(ServerUrlParseError):
    pass


class ServerUrlParseErrorScheme(ServerUrlParseError):
    pass


class ServerUrlParseErrorJustScheme(ServerUrlParseError):
    pass


class UnsupportedOperationException(Exception):
    """Thrown when a call is made that is unsupported in the current
    state.  For example, if a call is made to a deprecated API when
    a newer API is available.
    """

    pass


def has_bad_scheme(url):
    """Check a url for an invalid or unuseful schema.

    Don't allow urls to start with :/ http/ https/ non http/httpsm or http(s) with single /

    :params url: URL string to check
    :type url: str
    :returns: True if the url schme is "bad"
    :rtype: boolean
    """
    match_bad = r"(https?[:/])|(:/)|(\S+://)"
    match_good = r"https?://"
    # Testing good first allows us to exclude some regex for bad
    if re.match(match_good, url):
        return False
    if re.match(match_bad, url):
        return True
    return False


def has_good_scheme(url):
    match = re.match(r"https?://(\S+)?", url)
    if not match:
        return False
    # a good scheme alone is not really a good scheme
    if not match.group(1):
        raise ServerUrlParseErrorJustScheme(url)
    return True


def parse_url(
    local_server_entry,
    default_hostname=None,
    default_port=None,
    default_prefix=None,
    default_username=None,
    default_password=None,
):
    """
    Parse hostname, port, and webapp prefix from the string a user entered.

    Expected format: username:password@hostname:port/prefix

    Username, password, port and prefix are optional.

    :param local_server_entry: URL of a candlepin server
    :type: str
    :param default_hostname: default_hostname
    :param default_port: default_port
    :return: a tuple of (username, password, hostname, port, path)
    """
    # Adding http:// onto the front of the hostname

    if local_server_entry == "":
        raise ServerUrlParseErrorEmpty(local_server_entry)

    if local_server_entry is None:
        raise ServerUrlParseErrorNone(local_server_entry)

    # good_url in this case meaning a schema we support, and
    # _something_ else. This is to make urlparse happy
    good_url = None

    # handle any known or troublesome or bogus typo's, etc
    if has_bad_scheme(local_server_entry):
        raise ServerUrlParseErrorScheme(local_server_entry)

    # we want to see if we have a good scheme, and
    # at least _something_ else
    if has_good_scheme(local_server_entry):
        good_url = local_server_entry

    # not having a good scheme could just mean we don't have a scheme,
    # so let's include one so urlparse doesn't freak
    if not good_url:
        good_url = "https://%s" % local_server_entry

    # FIXME: need a try except here? docs
    # don't seem to indicate any expected exceptions
    result = urllib.parse.urlparse(good_url)
    username = default_username
    password = default_password

    # to support username and password, let's split on @
    # since the format will be username:password@hostname:port
    foo = result[1].split("@")

    # handle username/password portion, then deal with host:port
    # just in case someone passed in @hostname without
    # a username,  we default to the default_username
    if len(foo) > 1:
        creds = foo[0].split(":")
        netloc = foo[1].split(":")

        if len(creds) > 1:
            password = creds[1]
        if creds[0] is not None and len(creds[0]) > 0:
            username = creds[0]
    else:
        netloc = foo[0].split(":")

    # in some cases, if we try the attr accessors, we'll
    # get a ValueError deep down in urlparse, particular if
    # port ends up being None
    #
    # So maybe check result.port/path/hostname for None, and
    # throw an exception in those cases.
    # adding the schem seems to avoid this though
    port = default_port
    if len(netloc) > 1:
        if netloc[1] != "":
            port = str(netloc[1])
        else:
            raise ServerUrlParseErrorPort(local_server_entry)

    # path can be None?
    prefix = default_prefix
    if result[2] is not None:
        if result[2] != "":
            prefix = result[2]

    hostname = default_hostname
    if netloc[0] is not None:
        if netloc[0] != "":
            hostname = netloc[0]

    try:
        if port:
            int(port)
    except TypeError:
        raise ServerUrlParseErrorPort(local_server_entry)
    except ValueError:
        raise ServerUrlParseErrorPort(local_server_entry)

    return (username, password, hostname, port, prefix)


def get_env_proxy_info():
    the_proxy = {
        "proxy_username": "",
        "proxy_hostname": "",
        "proxy_port": "",
        "proxy_password": "",
    }

    # get the proxy information from the environment variable
    # if available
    # look in the following order:
    #   HTTPS_PROXY
    #   https_proxy
    #   HTTP_PROXY
    #   http_proxy
    # look through the list for the first one to match
    info = ()
    env_vars = ["HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy"]
    for ev in env_vars:
        proxy_info = os.getenv(ev)
        if proxy_info:
            info = parse_url(proxy_info, default_port=DEFAULT_PROXY_PORT)
            break

    if info:
        the_proxy["proxy_username"] = info[0]
        the_proxy["proxy_password"] = info[1]
        the_proxy["proxy_hostname"] = info[2]
        if info[3] is None or info[3] == "":
            the_proxy["proxy_port"] = None
        else:
            the_proxy["proxy_port"] = int(info[3])
    return the_proxy


def cmd_name(argv):
    """Attempt to get a meaningful command name from argv.

    This handles cases where argv[0] isn't helpful (for
    example, '/usr/bin/python' or '__main__.py'.
    """
    cmd_name_string = os.path.basename(argv[0])
    return cmd_name_string


def fix_no_proxy():
    """
    This fixes no_proxy/NO_PROXY environment to not include leading
    asterisk, because there is some imperfection in proxy_bypass_environment.
    """

    # This fixes BZ: 1443164, because proxy_bypass_environment() from urllib does
    # not support no_proxy with items containing asterisk (e.g.: *.redhat.com)

    no_proxy = os.environ.get("no_proxy") or os.environ.get("NO_PROXY")
    if no_proxy is not None:
        if no_proxy != "*":
            # Remove all leading white spaces and asterisks from items of no_proxy
            # except item containing only "*" (urllib supports alone asterisk).
            no_proxy = ",".join([item.lstrip(" *") for item in no_proxy.split(",")])
            # Save no_proxy back to 'no_proxy' and 'NO_PROXY'
            os.environ["no_proxy"] = no_proxy
            os.environ["NO_PROXY"] = no_proxy


def suppress_output(func):
    def wrapper(*args, **kwargs):
        try:
            devnull = open(os.devnull, "w")
            stdout = sys.stdout
            stderr = sys.stderr
            sys.stdout = devnull
            sys.stderr = devnull
            return func(*args, **kwargs)
        finally:
            sys.stdout = stdout
            sys.stderr = stderr
            devnull.close()

    return wrapper


def parse_bool(string: str) -> bool:
    """Parse a string into True or False.

    Recognized boolean pairs are 1/0, true/false, yes/no, on/off, case insensitive.

    :raises: ValueError if the string is not recognized.
    """
    string = string.lower()
    if string in ("1", "true", "yes", "on"):
        return True
    if string in ("0", "false", "no", "off"):
        return False
    raise ValueError(f"Value {string} is not recognized boolean value.")


def singleton(cls: type) -> type:
    """Decorate a class to make it singleton.

    This decorator is inherited: subclasses will be singletons as well,
    but they won't be the same singleton as their parent.
    """

    __orig_new__: Callable = cls.__new__
    cls._instance = None

    def __new__(kls, *args, **kwargs):
        if not isinstance(kls._instance, kls):
            if __orig_new__ is object.__new__:
                # Default __new__ only takes the class as an argument
                kls._instance = __orig_new__(kls)
            else:
                kls._instance = __orig_new__(kls, *args, **kwargs)
        return kls._instance

    cls.__new__ = __new__
    return cls


def call_once(fn: Callable) -> Callable:
    """Decorate a function to make it callable just once.

    All further calls do not do anything and return None.
    """
    fn._call_once_lock = threading.RLock()
    fn._called = False

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        locked: bool = fn._call_once_lock.acquire(blocking=True, timeout=1.0)
        if not locked:
            raise RuntimeError(f"Could not acquire call_once lock for function {fn.__name__}.")

        try:
            if fn._called:
                return None
            # We want to allow running the function once even if it raises exception.
            fn._called = True
            fn_result = fn(*args, **kwargs)
            return fn_result
        finally:
            fn._call_once_lock.release()

    def _reset():
        """Reset function state to allow another call to it.

        This is used for testing purposes, there is no need to call this in
        production code itself.
        """
        locked: bool = fn._call_once_lock.acquire(blocking=True, timeout=1.0)
        if not locked:
            raise RuntimeError(f"Could not acquire call_once lock for function {fn.__name__}.")

        try:
            fn._called = False
        finally:
            fn._call_once_lock.release()

    wrapper._reset = _reset

    return wrapper


def lock(cls: type) -> type:
    """Decorate a class to make it thread-safe lock.

    It will provide read-only 'locked' attribute, functions lock() and unlock()
    and __enter__/__exit__ methods for context manager functionality.
    """

    cls._lock = threading.RLock()
    """Actual lock providing locking functionality."""
    cls._locked = False
    """Even though _lock._is_owned() would work better,
    it is not part of public API, and it should not be used in production.
    """

    cls.locked = property(fget=lambda self: self._locked)

    def lock(self) -> None:
        """Lock using RLock.

        One thread can acquire the lock multiple times, but other threads cannot
        until the lock is completely unlocked.
        """
        self._lock.acquire()
        self._locked = True

    def unlock(self) -> None:
        """Unlock the lock."""
        try:
            self._lock.release()
        except RuntimeError:
            # This exception is raised when the lock was not acquired
            pass
        finally:
            self._locked = False

    def __enter__(self) -> cls:
        self.lock()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.unlock()

    cls.lock = lock
    cls.unlock = unlock
    cls.__enter__ = __enter__
    cls.__exit__ = __exit__

    return cls


class StatusMessage:
    """Class for temporary reporting.

    While you can call 'print()' and 'clean()' methods directly, the easier
    way is to use context manager: 'with StatusMessage("Fetching data"):'.

    This object will print the description to stdout when called. When the
    context manager exists (either because the code finished or because an
    error got raised inside), printed output will be cleared before the
    program continues with its execution. This ensures that the message will
    disappear after it's no longer valid.
    """

    def __init__(self, description: Optional[str]):
        if description is None:
            description = "Transmitting data"
        self.raw_text = description

        CURSIVE = "\033[3m"
        RESET = "\033[0m"

        self.text = f"{CURSIVE}{self.raw_text}{RESET}"

        self.quiet = False
        config = rhsm.config.get_config_parser()
        if config.get("rhsm", "progress_messages") == "0":
            self.quiet = True
        if not PROGRESS_MESSAGES:
            self.quiet = True
        if not sys.stdout.isatty():
            self.quiet = True
        if parse_bool(os.environ.get("SUBMAN_DEBUG_PRINT_REQUEST", "0")):
            self.quiet = True

    def print(self):
        if self.quiet:
            return
        print(self.text, end="\r")

    def clean(self):
        if self.quiet:
            return
        print(" " * len(self.text), end="\r")

    def __enter__(self):
        self.print()

    def __exit__(self, error_type, error_value, traceback):
        self.clean()
        if error_type:
            raise


class StatusSpinnerStyle:
    """Class for spinner animations.

    While subscription-manager may not be using all spinners used below,
    they have been defined here, so they can be easily used in the future.

    The default spinner, LINE, has been chosen for several reasons:
    - it is small (only one character wide),
    - it has small loop cycle (so quickly switching several status messages
      looks like it is one spinner with several messages, even though every
      message has its own spinner),
    - it is only made of ASCII characters (which makes it renderable on
      all TTYs, not just rich terminal emulators in GUI).
    """

    LINE: List[str] = ["|", "/", "-", "\\"]
    BRAILLE: List[str] = ["⠋", "⠙", "⠸", "⠴", "⠦", "⠇"]
    WIDE_BRAILLE: List[str] = ["⠧ ", "⠏ ", "⠋⠁", "⠉⠉", "⠈⠙", " ⠹", " ⠼", "⠠⠴", "⠤⠤", "⠦⠄"]
    BAR_FORWARD: List[str] = ["[    ]", "[=   ]", "[==  ]", "[=== ]", "[====]", "[ ===]", "[  ==]", "[   =]"]
    BAR_BACKWARD: List[str] = ["[    ]", "[   =]", "[  ==]", "[ ===]", "[====]", "[=== ]", "[==  ]", "[=   ]"]
    BAR_BOUNCE: List[str] = BAR_FORWARD + BAR_BACKWARD


class LiveStatusMessage(StatusMessage):
    """Class for temporary reporting, with activity spinner.

    While you can call 'print()' and 'clean()' methods directly, the easier
    way is to use context manager: 'with LiveStatusMessage("Fetching data"):'.

    This object will print the description to stdout when called. When the
    context manager exists (either because the code finished or because an
    error got raised inside), printed output will be cleared before the
    program continues with its execution. This ensures that the message will
    disappear after it's no longer valid.

    You can set several loading styles (via class StatusSpinnerStyle) or choose
    the speed in which the animation is played (per frame, in seconds).
    """

    def __init__(
        self,
        description: Optional[str],
        *,
        style: List[str] = StatusSpinnerStyle.LINE,
        placement: str = "BEFORE",
        speed: float = 0.15,
    ):
        super().__init__(description)

        # Do not use cursive if there is a spinner. When the message is
        # displayed without the spinner (using plain StatusMessage class)
        # the cursive is used to visually separate the status message from
        # real output. When we have a spinner, it is not necessary, because
        # the spinner itself is making that visual difference.
        self.text = self.raw_text

        self.busy: bool = False
        self._loops: int = 0
        self._thread: threading.Thread = None
        self._cursor: bool = True

        self.frames: str = style
        self.delay: float = speed
        if placement not in ("BEFORE", "AFTER"):
            raise ValueError(f"String {placement} is not valid spinner placement.")
        self.placement: str = placement

    @property
    def spinner_frame(self):
        """Get next frame of the spinner annimation."""
        while True:
            yield self.frames[self._loops % len(self.frames)]

    @property
    def max_text_width(self) -> int:
        """Get the length of the longest line possible.

        This is used so we can properly clean the console when we exit.
        """
        max_frame_length: int = len(max(self.frames, key=len))
        return len(self.text) + max_frame_length + 1

    @property
    def cursor(self) -> bool:
        """Get cursor visibility state."""
        return self._cursor

    @cursor.setter
    def cursor(self, enable: bool):
        """Enable or disable cursor.

        For more information on these rarely used shell escape codes, see
        https://en.wikipedia.org/wiki/ANSI_escape_code#CSI_(Control_Sequence_Introducer)_sequences
        """
        if type(enable) is not bool:
            raise ValueError(f"Expected bool, got {type(enable)!s}")
        if enable:
            print("\033[?25h", end="")
            self._cursor = True
        else:
            print("\033[?25l", end="")
            self._cursor = False

    def __enter__(self):
        self.busy = True
        if self.quiet:
            return
        self.cursor = False
        self._thread = threading.Thread(target=self.loop)
        self._thread.start()

    def __exit__(self, error_type, error_value, traceback):
        self.busy = False
        if self.quiet:
            if error_type:
                raise
            return
        self.cursor = True
        self._thread.join(timeout=self.delay)
        if error_type:
            raise

    def print(self):
        if self.quiet:
            return
        frame: str = next(self.spinner_frame)
        line: str
        if self.placement == "BEFORE":
            line = frame + " " + self.text
        else:
            line = self.text + " " + frame
        print(line, end="\r")

    def clean(self):
        if self.quiet:
            return
        print(" " * self.max_text_width, end="\r")

    def loop(self):
        """Show pretty animation while we fetch data."""
        while self.busy:
            self.print()
            self._loops += 1
            time.sleep(self.delay)
            self.clean()
