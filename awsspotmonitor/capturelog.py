from __future__ import absolute_import
from __future__ import print_function

# standard
from datetime import datetime
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
import smtplib
import socket
from StringIO import StringIO
import sys
import traceback


class CaptureLog(object):
    """Captures messages and optionally emails them to the specified recipients.

    The CaptureLog can be switched between capturing and not-capturing. When not-capturing,
    messages are simply written to stdout by calling print(). When capturing, messages are
    also written to stdout, and they're also stored internally. When capturing is ended,
    the stored log is (optionally) emailed to a specified recipient before it's deleted.

    Mail configuration, if specified, is a dictionary with the following keys:
        subject: the subject for the log message (string)
        sender: address of the sender (string or tuple),
                if a tuple: (sender-name, sender-email), e.g., ('me', 'me@home.com')
        recipients: email address(es) to whom the mail should be sent (string or list of strings)
        host: name of the SMTP host (default: 'localhost')
        port: name of the host port (default: 25)
        use_ssl: True to use SSL (default: False)
        use_tls: True to use TLS (default: False)
        debug: True to set the SMTP library debug flag (default: False)
        username: username for login to the SMTP host (default: None)
        password: password for login to the SMTP host (default: None)
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

        self.write('---------- LOG CLOSED AT: {0} UTC'.format(datetime.utcnow().isoformat()))
        text = self._log.getvalue()
        self._log = None
        if self._mail_cfg:
            print('SENDING LOG.')
            self._send_msg(*self._create_log_msg(text))

    def file(self):
        return self._log if self._log else sys.stdout

    def start_capture(self):
        self._log = StringIO()
        self.write('---------- LOG STARTED AT: {0} UTC'.format(datetime.utcnow().isoformat()))

    def write(self, *args, **kwargs):
        print(*args, **kwargs)
        if self.capturing:
            print(*args, file=self.file(), **kwargs)

    def _create_log_msg(self, msg_text):
        msg = MIMEText(msg_text, _subtype='plain', _charset='utf-8')

        sender = self._mail_cfg['sender']
        if isinstance(sender, tuple):
            sender = '%s <%s>' % sender

        recipients = self._mail_cfg['recipients']
        if isinstance(recipients, basestring):
            recipients = [recipients]

        msg['Subject'] = self._mail_cfg['subject']
        msg['From'] = sender
        msg['To'] = ', '.join(recipients)
        msg['Date'] = formatdate()
        msg['Message-ID'] = make_msgid()
        return sender, recipients, msg

    def _send_msg(self, sender, recipients, msg):
        host = None
        try:
            host = self._mail_cfg.get('host', 'localhost')
            port = self._mail_cfg.get('port', 25)
            if self._mail_cfg.get('use_ssl', False):
                host = smtplib.SMTP_SSL(host, port)
            else:
                host = smtplib.SMTP(host, port)

            host.set_debuglevel(int(self._mail_cfg.get('debug', 0)))
            if self._mail_cfg.get('use_tls', False):
                host.starttls()

            username = self._mail_cfg.get('username', None)
            password = self._mail_cfg.get('password', None)
            if username and password:
                host.login(username, password)

            host.sendmail(sender, recipients, msg.as_string())
        except socket.error:
            traceback.print_exc()
        finally:
            if host:
                host.quit()
