from __future__ import absolute_import
from __future__ import print_function

# standard
from datetime import datetime
from StringIO import StringIO
import sys

# package.
from .msg_util import *


class CaptureLog(object):
    """Captures messages and optionally emails them to the specified recipients.

    The CaptureLog can be switched between capturing and not-capturing. When not-capturing,
    messages are simply written to stdout by calling print(). When capturing, messages are
    also written to stdout, and they're also stored internally. When capturing is ended,
    the stored log is (optionally) emailed to a specified recipient before it's deleted.

    Mail configuration, if specified, is a dictionary like that used with send_msg() and
    with these additional keys:
        subject: the subject for the log message (string)
        sender: address of the sender (string or tuple);
                if a tuple: (sender-name, sender-email), e.g., ('me', 'me@home.com').
        recipients: email address(es) to whom the mail should be sent (string or list of strings).
    """
    @property
    def capturing(self):
        return self._log is not None

    def __init__(self, mail_config=None):
        self._log = None
        self._mail_cfg = mail_config

    def end_capture(self):
        if not self._log:
            return

        self.write('---------- LOG ENDED AT: {0} UTC'.format(datetime.utcnow().isoformat()))
        text = self._log.getvalue()
        self._log = None
        if self._mail_cfg:
            print('SENDING LOG.')
            send_plaintext_msg(
                self._mail_cfg,
                *create_plaintext_msg(
                    self._mail_cfg['subject'],
                    self._mail_cfg['sender'],
                    self._mail_cfg['recipients'],
                    text))

    def file(self):
        return self._log if self._log else sys.stdout

    def start_capture(self):
        self._log = StringIO()
        self.write('---------- LOG STARTED AT: {0} UTC'.format(datetime.utcnow().isoformat()))

    def write(self, *args, **kwargs):
        print(*args, **kwargs)
        if self.capturing:
            print(*args, file=self.file(), **kwargs)
