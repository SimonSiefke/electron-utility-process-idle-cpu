"""Darwin process-wide CPU and instruction counters, read externally via libproc.

Layout: Apple's xnu/bsd/sys/resource.h, struct rusage_info_v4 (RUSAGE_INFO_V4=4).
https://github.com/apple-oss-distributions/xnu/blob/main/bsd/sys/resource.h
"""
import ctypes


class RusageInfoV4(ctypes.Structure):
    _fields_ = [('uuid', ctypes.c_uint8 * 16)] + [(name, ctypes.c_uint64) for name in (
        'user_time system_time pkg_idle_wkups interrupt_wkups pageins wired_size '
        'resident_size phys_footprint proc_start_abstime proc_exit_abstime '
        'child_user_time child_system_time child_pkg_idle_wkups child_interrupt_wkups '
        'child_pageins child_elapsed_abstime diskio_bytesread diskio_byteswritten '
        'cpu_time_qos_default cpu_time_qos_maintenance cpu_time_qos_background '
        'cpu_time_qos_utility cpu_time_qos_legacy cpu_time_qos_user_initiated '
        'cpu_time_qos_user_interactive billed_system_time serviced_system_time '
        'logical_writes lifetime_max_phys_footprint instructions cycles billed_energy '
        'serviced_energy interval_max_phys_footprint runnable_time'
    ).split()]


_libproc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
_libproc.proc_pid_rusage.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_void_p]
_libproc.proc_pid_rusage.restype = ctypes.c_int


def snapshot(pid):
    info = RusageInfoV4()
    if _libproc.proc_pid_rusage(pid, 4, ctypes.byref(info)) != 0:
        error = ctypes.get_errno()
        raise OSError(error, f'proc_pid_rusage failed for {pid}')
    return {'cpu_ns': info.user_time + info.system_time,
            'instructions': info.instructions, 'cycles': info.cycles,
            'idle_wakeups': info.pkg_idle_wkups}
