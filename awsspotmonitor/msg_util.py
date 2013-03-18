from __future__ import absolute_import

# standard
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
import smtplib
import socket
import traceback


def create_plaintext_msg(subject, sender, recipients, msg_text):
    msg = MIMEText(msg_text, _subtype='plain', _charset='utf-8')

    if isinstance(sender, tuple):
        sender = '%s <%s>' % sender

    if isinstance(recipients, basestring):
        recipients = [recipients]

    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = ', '.join(recipients)
    msg['Date'] = formatdate()
    msg['Message-ID'] = make_msgid()
    return sender, recipients, msg


def send_plaintext_msg(config, sender, recipients, msg):
    """Sends a simple plaintext email message.

    Sends a plaintext email message to the specified recipients, using the specified
    mail host.

    :param config: a dictionary with the following keys:
        host: name of the SMTP host (default: 'localhost')
        port: name of the host port (default: 25)
        use_ssl: True to use SSL (default: False)
        use_tls: True to use TLS (default: False)
        debug: True to set the SMTP library debug flag (default: False)
        username: username for login to the SMTP host (default: None)
        password: password for login to the SMTP host (default: None)
    :param sender: address of the sender (string or tuple);
                   if a tuple: (sender-name, sender-email), e.g., ('me', 'me@home.com').
    :param recipients: email address(es) to whom the mail should be sent (string or list of strings).
    :param msg: the text of the message to send.
    """
    host = None
    try:
        host = config.get('host', 'localhost')
        port = config.get('port', 25)
        if config.get('use_ssl', False):
            host = smtplib.SMTP_SSL(host, port)
        else:
            host = smtplib.SMTP(host, port)

        host.set_debuglevel(int(config.get('debug', 0)))
        if config.get('use_tls', False):
            host.starttls()

        username = config.get('username', None)
        password = config.get('password', None)
        if username and password:
            host.login(username, password)

        host.sendmail(sender, recipients, msg.as_string())
    except socket.error:
        traceback.print_exc()
    finally:
        if host:
            host.quit()


