"""Cygwin platform implementation."""

# TODO: Large chunks of this module are copy/pasted from the Linux module;
# seek out further opportunities for refactoring

from __future__ import division

import errno
import os
import re
import sys
from collections import namedtuple

from . import _common
from . import _psposix
from . import _psutil_cygwin as cext
from . import _psutil_posix as cext_posix
from ._common import decode
from ._common import get_procfs_path
from ._common import isfile_strict
from ._common import open_binary
from ._common import open_text
from ._common import popenfile
from ._common import wrap_exceptions
from ._compat import PY3

if sys.version_info >= (3, 4):
    import enum
else:
    enum = None

__extra__all__ = ["PROCFS_PATH"]


# =====================================================================
# --- constants
# =====================================================================


if enum is None:
    AF_LINK = -1
else:
    AddressFamily = enum.IntEnum('AddressFamily', {'AF_LINK': -1})
    AF_LINK = AddressFamily.AF_LINK


# Number of clock ticks per second
CLOCK_TICKS = os.sysconf("SC_CLK_TCK")
PAGESIZE = os.sysconf("SC_PAGE_SIZE")
BOOT_TIME = None  # set later


# TODO: Update me to properly reflect Cygwin-recognized process statuses
# taken from /fs/proc/array.c
PROC_STATUSES = {
    "R": _common.STATUS_RUNNING,
    "S": _common.STATUS_SLEEPING,
    "D": _common.STATUS_DISK_SLEEP,
    "T": _common.STATUS_STOPPED,
    "t": _common.STATUS_TRACING_STOP,
    "Z": _common.STATUS_ZOMBIE,
    "X": _common.STATUS_DEAD,
    "x": _common.STATUS_DEAD,
    "K": _common.STATUS_WAKE_KILL,
    "W": _common.STATUS_WAKING
}


# =====================================================================
# -- exceptions
# =====================================================================


# these get overwritten on "import psutil" from the __init__.py file
NoSuchProcess = None
ZombieProcess = None
AccessDenied = None
TimeoutExpired = None


# =====================================================================
# --- named tuples
# =====================================================================


scputimes = namedtuple('scputimes', ['user', 'system', 'idle'])
pmem = namedtuple('pmem', 'rss vms shared text lib data dirty')


# =====================================================================
# --- CPUs
# =====================================================================


def cpu_times():
    """Return a named tuple representing the following system-wide
    CPU times:
    (user, nice, system, idle, iowait, irq, softirq [steal, [guest,
     [guest_nice]]])
    Last 3 fields may not be available on all Linux kernel versions.
    """
    procfs_path = get_procfs_path()
    with open_binary('%s/stat' % procfs_path) as f:
        values = f.readline().split()
    fields = values[1:2] + values[3:len(scputimes._fields) + 2]
    fields = [float(x) / CLOCK_TICKS for x in fields]
    return scputimes(*fields)


def per_cpu_times():
    """Return a list of namedtuple representing the CPU times
    for every CPU available on the system.
    """
    procfs_path = get_procfs_path()
    cpus = []
    with open_binary('%s/stat' % procfs_path) as f:
        # get rid of the first line which refers to system wide CPU stats
        f.readline()
        for line in f:
            if line.startswith(b'cpu'):
                values = line.split()
                fields = values[1:2] + values[3:len(scputimes._fields) + 2]
                fields = [float(x) / CLOCK_TICKS for x in fields]
                entry = scputimes(*fields)
                cpus.append(entry)
        return cpus


# =====================================================================
# --- other system functions
# =====================================================================


def boot_time():
    """Return the system boot time expressed in seconds since the epoch."""
    global BOOT_TIME
    with open_binary('%s/stat' % get_procfs_path()) as f:
        for line in f:
            if line.startswith(b'btime'):
                ret = float(line.strip().split()[1])
                BOOT_TIME = ret
                return ret
        raise RuntimeError(
            "line 'btime' not found in %s/stat" % get_procfs_path())


# =====================================================================
# --- processes
# =====================================================================


class Process(object):
    """Cygwin process implementation."""

    __slots__ = ["pid", "_name", "_ppid", "_procfs_path"]

    def __init__(self, pid):
        self.pid = pid
        self._name = None
        self._ppid = None
        self._procfs_path = get_procfs_path()

    def _parse_stat_file(self):
        """Parse /proc/{pid}/stat file. Return a list of fields where
        process name is in position 0.
        Using "man proc" as a reference: where "man proc" refers to
        position N, always subscract 2 (e.g starttime pos 22 in
        'man proc' == pos 20 in the list returned here).
        """
        with open_binary("%s/%s/stat" % (self._procfs_path, self.pid)) as f:
            data = f.read()
        # Process name is between parentheses. It can contain spaces and
        # other parentheses. This is taken into account by looking for
        # the first occurrence of "(" and the last occurence of ")".
        rpar = data.rfind(b')')
        name = data[data.find(b'(') + 1:rpar]
        fields_after_name = data[rpar + 2:].split()
        return [name] + fields_after_name

    def _read_status_file(self):
        with open_binary("%s/%s/status" % (self._procfs_path, self.pid)) as f:
            return f.read()

    @wrap_exceptions
    def name(self):
        name = self._parse_stat_file()[0]
        if PY3:
            name = decode(name)
        # XXX - gets changed later and probably needs refactoring
        return name

    def exe(self):
        try:
            return os.readlink("%s/%s/exe" % (self._procfs_path, self.pid))
        except OSError as err:
            if err.errno in (errno.ENOENT, errno.ESRCH):
                # no such file error; might be raised also if the
                # path actually exists for system processes with
                # low pids (about 0-20)
                if os.path.lexists("%s/%s" % (self._procfs_path, self.pid)):
                    return ""
                else:
                    if not _psposix.pid_exists(self.pid):
                        raise NoSuchProcess(self.pid, self._name)
                    else:
                        raise ZombieProcess(self.pid, self._name, self._ppid)
            if err.errno in (errno.EPERM, errno.EACCES):
                raise AccessDenied(self.pid, self._name)
            raise

    @wrap_exceptions
    def cmdline(self):
        with open_text("%s/%s/cmdline" % (self._procfs_path, self.pid)) as f:
            data = f.read()
        if not data:
            # may happen in case of zombie process
            return []
        if data.endswith('\x00'):
            data = data[:-1]
        return [x for x in data.split('\x00')]

    @wrap_exceptions
    def environ(self):
        raise NotImplementedError("environ implemented on Cygwin (yet)")

    @wrap_exceptions
    def terminal(self):
        tty_nr = int(self._parse_stat_file()[5])
        tmap = _psposix.get_terminal_map()
        try:
            return tmap[tty_nr]
        except KeyError:
            return None

    def io_counters(self):
        raise NotImplementedError("io_counters not implemented on Cygwin "
                                  "(yet)")

    @wrap_exceptions
    def cpu_times(self):
        values = self._parse_stat_file()
        utime = float(values[12]) / CLOCK_TICKS
        stime = float(values[13]) / CLOCK_TICKS
        children_utime = float(values[14]) / CLOCK_TICKS
        children_stime = float(values[15]) / CLOCK_TICKS
        return _common.pcputimes(utime, stime, children_utime, children_stime)

    @wrap_exceptions
    def wait(self, timeout=None):
        try:
            return _psposix.wait_pid(self.pid, timeout)
        except _psposix.TimeoutExpired:
            raise TimeoutExpired(timeout, self.pid, self._name)

    @wrap_exceptions
    def create_time(self):
        values = self._parse_stat_file()
        # According to source, starttime is in field 22 and the
        # unit is jiffies (clock ticks).
        # We first divide it for clock ticks and then add uptime returning
        # seconds since the epoch, in UTC.
        # Also use cached value if available.
        bt = BOOT_TIME or boot_time()
        return (float(values[21]) / CLOCK_TICKS) + bt

    @wrap_exceptions
    def memory_info(self):
        #  ============================================================
        # | FIELD  | DESCRIPTION                         | AKA  | TOP  |
        #  ============================================================
        # | rss    | resident set size                   |      | RES  |
        # | vms    | total program size                  | size | VIRT |
        # | shared | shared pages (from shared mappings) |      | SHR  |
        # | text   | text ('code')                       | trs  | CODE |
        # | lib    | library (unused in Linux 2.6)       | lrs  |      |
        # | data   | data + stack                        | drs  | DATA |
        # | dirty  | dirty pages (unused in Linux 2.6)   | dt   |      |
        #  ============================================================
        with open_binary("%s/%s/statm" % (self._procfs_path, self.pid)) as f:
            vms, rss, shared, text, lib, data, dirty = \
                [int(x) * PAGESIZE for x in f.readline().split()[:7]]
        return pmem(rss, vms, shared, text, lib, data, dirty)

    memory_full_info = memory_info

    def memory_maps(self):
        raise NotImplementedError("memory_maps not implemented on Cygwin "
                                  "(yet)")

    @wrap_exceptions
    def cwd(self):
        return os.readlink("%s/%s/cwd" % (self._procfs_path, self.pid))

    @wrap_exceptions
    def num_ctx_switches(self, _ctxsw_re=re.compile(b'ctxt_switches:\t(\d+)')):
        raise NotImplementedError("num_ctx_switches not implemented on Cygwin "
                                  "(yet)")

    @wrap_exceptions
    def num_threads(self, _num_threads_re=re.compile(b'Threads:\t(\d+)')):
        raise NotImplementedError("num_threads not implemented on Cygwin "
                                  "(yet)")

    @wrap_exceptions
    def threads(self):
        raise NotImplementedError("threads not implemented on Cygwin (yet)")

    @wrap_exceptions
    def nice_get(self):
        # Use C implementation
        return cext_posix.getpriority(self.pid)

    @wrap_exceptions
    def nice_set(self, value):
        return cext_posix.setpriority(self.pid, value)

    @wrap_exceptions
    def cpu_affinity_get(self):
        return cext.proc_cpu_affinity_get(self.pid)

    @wrap_exceptions
    def cpu_affinity_set(self, cpus):
        try:
            cext.proc_cpu_affinity_set(self.pid, cpus)
        except (OSError, ValueError) as err:
            if isinstance(err, ValueError) or err.errno == errno.EINVAL:
                allcpus = tuple(range(len(per_cpu_times())))
                for cpu in cpus:
                    if cpu not in allcpus:
                        raise ValueError(
                            "invalid CPU number %r; choose between %s" % (
                                cpu, allcpus))
            raise

    @wrap_exceptions
    def status(self):
        letter = self._parse_stat_file()[1]
        if PY3:
            letter = letter.decode()
        # XXX is '?' legit? (we're not supposed to return it anyway)
        return PROC_STATUSES.get(letter, '?')

    @wrap_exceptions
    def open_files(self):
        retlist = []
        files = os.listdir("%s/%s/fd" % (self._procfs_path, self.pid))
        hit_enoent = False
        for fd in files:
            file = "%s/%s/fd/%s" % (self._procfs_path, self.pid, fd)
            try:
                path = os.readlink(file)
            except OSError as err:
                # ENOENT == file which is gone in the meantime
                if err.errno in (errno.ENOENT, errno.ESRCH):
                    hit_enoent = True
                    continue
                elif err.errno == errno.EINVAL:
                    # not a link
                    continue
                else:
                    raise
            else:
                # If path is not an absolute there's no way to tell
                # whether it's a regular file or not, so we skip it.
                # A regular file is always supposed to be have an
                # absolute path though.
                if path.startswith('/') and isfile_strict(path):
                    ntuple = popenfile(path, int(fd))
                    retlist.append(ntuple)
        if hit_enoent:
            # raise NSP if the process disappeared on us
            os.stat('%s/%s' % (self._procfs_path, self.pid))
        return retlist

    @wrap_exceptions
    def connections(self, kind='inet'):
        # Note: Cygwin *does* have a /proc/net but I don't know that it's
        # equivalent to the /proc/net on Linux
        raise NotImplementedError("connections not implemented on Cygwin "
                                  "(yet)")

    @wrap_exceptions
    def num_fds(self):
        return len(os.listdir("%s/%s/fd" % (self._procfs_path, self.pid)))

    @wrap_exceptions
    def ppid(self):
        return int(self._parse_stat_file()[2])

    @wrap_exceptions
    def uids(self, _uids_re=re.compile(b'Uid:\t(\d+)\t(\d+)\t(\d+)')):
        data = self._read_status_file()
        real, effective, saved = _uids_re.findall(data)[0]
        return _common.puids(int(real), int(effective), int(saved))

    @wrap_exceptions
    def gids(self, _gids_re=re.compile(b'Gid:\t(\d+)\t(\d+)\t(\d+)')):
        data = self._read_status_file()
        real, effective, saved = _gids_re.findall(data)[0]
        return _common.pgids(int(real), int(effective), int(saved))
