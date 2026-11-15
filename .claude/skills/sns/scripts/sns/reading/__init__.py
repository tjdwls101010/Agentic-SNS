"""The shared reading pipeline every platform's commands run through: the platform adapter, the guarded connection,
handles, --out files, list paging with date windows, composite sections, doctor and the idle cleanup."""
from sns.reading.care import doctor, idle
from sns.reading.pipeline import (EMPTY_SNIPPETS, IDLE_SECONDS, Connection, context, empty_tab, read_list, run, section,
                                  stops_continuing)
from sns.reading.pictures import IMAGE_SCHEMA, pictures
from sns.reading.platform import Invocation, Platform, foreign
from sns.reading.state import adopt, adopt_all

__all__ = ['adopt', 'adopt_all', 'EMPTY_SNIPPETS', 'IDLE_SECONDS', 'IMAGE_SCHEMA', 'pictures', 'Connection', 'Invocation', 'Platform', 'context', 'doctor', 'empty_tab', 'foreign', 'idle',
           'read_list', 'run', 'section', 'stops_continuing']
