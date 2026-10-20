"""The shared reading pipeline every platform's commands run through: the platform adapter, the guarded connection,
handles, --out files, list paging with date windows, composite sections, doctor and the idle cleanup."""
from sns.reading.care import doctor, idle
from sns.reading.pipeline import IDLE_SECONDS, Connection, context, empty_tab, read_list, run, section
from sns.reading.platform import Invocation, Platform, foreign

__all__ = ['IDLE_SECONDS', 'Connection', 'Invocation', 'Platform', 'context', 'doctor', 'empty_tab', 'foreign', 'idle',
           'read_list', 'run', 'section']
