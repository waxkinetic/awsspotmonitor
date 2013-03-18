from __future__ import absolute_import

# standard
from mock import patch
import unittest

# package
from .capturelog import *


class CaptureLog_test(unittest.TestCase):
    def test_create_msg(self):
        mail_config = dict(
            subject = 'email subject',
            sender = ('Rick', 'waxkinetic@gmail.com'),
            recipients = ['borick@gmail.com', 'waxkinetic@gmail.com']
        )

        log = CaptureLog(mail_config)
        with patch('awsspotmonitor.capturelog.send_plaintext_msg') as send_msg:
            log.start_capture()
            log.write('first message')
            log.write('second message')
            log.end_capture()
            send_msg.assert_called_once()
            args, _ = send_msg.call_args
            self.assertEqual(args[1], 'Rick <waxkinetic@gmail.com>')
            self.assertEqual(args[2], mail_config['recipients'])


if __name__ == '__main__':
    unittest.main()
