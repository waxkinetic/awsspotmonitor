from __future__ import absolute_import
from __future__ import print_function

# standard
from collections import namedtuple
from datetime import datetime, timedelta
import os
import random
import time
import traceback

# pypi
import boto.ec2
from boto.exception import EC2ResponseError

# package
from .capturelog import CaptureLog


__all__ = ['AwsSpotMonitor']


class Request(object):
    """Class to simplify processing of EC2 spot-instance requests.

    The Request class mostly helps rationalize the spot-request status by lumping them
    together into the states identified by Request.State. Of these, the pending, holding,
    and fulfilled states are the most interesting.

    Also, here are some notes of interest:

    1. The spot-request is not a good indicator of instance termination, it usually lags
       far behind. Earlier detection is done by looking at instances themselves.

    2. The 'marked-for-termination' status is usually missed unless polling occurs at
       the right moment. However, when this status is detected it is distinguishable.
    """
    DATE_TAG = 'req_date'
    DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S'

    State = namedtuple('State', 'Dead, Terminated, Pending, Holding, Fulfilled, Marked')(
        Dead = 0,
        Terminated = 1,
        Pending = 2,
        Holding = 3,
        Fulfilled = 4,
        Marked = 5
    )

    @property
    def last_date(self):
        if self._dt is None:
            s = self.req.tags.get(self.DATE_TAG, None)
            self._dt = datetime.strptime(s.strip(), self.DATETIME_FORMAT) if s else None
        return self._dt

    def __init__(self, boto_req):
        self.req = boto_req
        self._dt = None
        self._state = None

    def state(self):
        # use cached state if possible.
        if self._state:
            return self._state

        if self.req.status.code in (
                'marked-for-termination'):
            self._state = self.State.Marked
        elif self.req.status.code in (
                'instance-terminated-by-price'
                'instance-terminated-by-user',
                'spot-instance-terminated-by-user',
                'instance-terminated-no-capacity',
                'instance-terminated-capacity-oversubscribed',
                'instance-terminated-launch-group-constraint'):
            self._state = self.State.Terminated
        elif self.req.status.code in (
                'pending-evaluation',
                'pending-fulfillment'):
            self._state = self.State.Pending
        elif self.req.status.code in (
                'capacity-not-available',
                'capacity-oversubscribed',
                'price-too-low',
                'not-scheduled-yet',
                'launch-group-constraint',
                'az-group-constraint',
                'placement-group-constraint',
                'constraint-not-fulfillable'):
            self._state = self.State.Holding
        elif self.req.status.code in (
                'fulfilled',
                'request-canceled-and-instance-running'):
            self._state = self.State.Fulfilled
        else:
            self._state = self.State.Dead

        return self._state

    def mark(self):
        s = datetime.utcnow().strftime(self.DATETIME_FORMAT)
        print('marking {0} with {1}'.format(self.req.id, s))
        self.req.add_tag(self.DATE_TAG, s)


class AwsSpotMonitor(object):
    DEFAULT_CONFIG = dict(
        region_name = 'us-east-1',

        # parameters for pricing query.
        availability_zone = None,
        instance_type = 't1.micro',
        product_description = 'Linux/UNIX',

        # Amazon Linux AMI.
        ami_id = 'ami-54cf5c3d',

        # security/firewall.
        key_pair_name = None,       # key-pair name
        security_groups = None,     # list of group names

        # price/bid strategy: ['high' | 'average-high' | 'average' | 'random']
        # use 'high' or 'average-high' for best chance of fulfillment.
        # 'random' strategy really only useful for test/debug.
        price_strategy = 'average-high'
    )

    @classmethod
    def create(cls, key_pair_name, security_groups):
        if isinstance(security_groups, basestring):
            security_groups = [security_groups]
        dct = cls.DEFAULT_CONFIG.copy()
        dct['key_pair_name'] = key_pair_name
        dct['security_groups'] = security_groups
        return cls(dct)

    def __init__(self, config=None, mail_config=None):
        self._config = config if config else self.DEFAULT_CONFIG.copy()
        self._conn = boto.ec2.connect_to_region(self._config['region_name'],
            aws_access_key_id=os.environ['AWS_ACCESS_KEY_ID'],
            aws_secret_access_key=os.environ['AWS_SECRET_ACCESS_KEY'])
        self._last_checkpoint = None
        self._log = CaptureLog(mail_config)
        random.jumpahead(int(os.getpid()))

    def check_requests(self):
        """Reviews the status of all spot-instance requests.

        For newly fulfilled requests, the process_fulfilled() method is called.

        If there are too few running spot instances, further action is taken: requests that
        have gone into the holding state are canceled, and if there are no pending requests a
        new spot-request is submitted.

        :return: None
        """
        self._log.write('-----\ncheck requests:')
        # process newly fulfilled requests.
        reqs = self._bucket_requests()
        for r in reqs[Request.State.Fulfilled]:
            if r.last_date is None:
                self.process_fulfilled(r.req)
                r.mark()

        # if not enough instances running, see if action is needed. note that a request
        # that's marked for termination is treated as terminated.
        instances = self._get_active_instances()
        if (len(instances)-len(reqs[Request.State.Marked])) < 1:
            if not self._log.capturing:
                self._log.start_capture()
            self._log.write('not enough running instances.')
            price = 0
            for r in reqs[Request.State.Holding]:
                self._log.write('cancelling request: {0}, price={1}, status={2}'
                                .format(r.req.id, r.req.price, r.req.status))
                price = max(price, r.req.price)
                r.req.cancel()

            # if no remaining active requests, submit one.
            if not reqs[Request.State.Pending]:
                self.request_instance(price)
        elif self._log.capturing:
            self._log.end_capture()

    def get_price_info(self, days=5):
        """Retrieves historic price information.

        Retrieves historic price information for the specified number of days, and returns
        the low, high and average price.

        :param days: the number of days to look back (default: 5).
        :return: tuple: (low, high, average) price
        """
        start = datetime.now() - timedelta(days=days)
        items = self._conn.get_spot_price_history(start_time=start.isoformat(),
                                                  availability_zone=self._config['availability_zone'],
                                                  instance_type=self._config['instance_type'],
                                                  product_description=self._config['product_description'])
        # compute stats.
        high=0.0
        low=10.0
        sum=0.0
        for item in items:
            if item.price > high:
                high = item.price
            if item.price < low:
                low = item.price
            sum += item.price
        avg = sum/len(items)
        return (low, high, avg)

    def loop(self, wait_secs=180):
        """Periodically checks request status.

        Simple loop that calls check_requests() then sleeps for a specific length of time.

        :param wait_secs: seconds to wait between checks (default: 60).
        :return: None
        """
        while True:
            try:
                self.check_requests()
                time.sleep(wait_secs)
            except KeyboardInterrupt:
                print('...got CTRL+C; exiting loop')
                break

    def process_fulfilled(self, req):
        """Process a newly fulfilled instance.

        Processes an EC2 instance created as a result of a newly fulfilled spot-instance request.
        This method is intended to be overridden by derived classes, but those implementations
        MUST ALSO call the base class implementation.

        :param req: boto.ec2.spotinstancerequest
        :return: None
        """
        self._log.write('FULFILLED {req.id}: instance-id={req.instance_id}, price={req.price}'
                        .format(**locals()))
        pass

    def request_instance(self, recent_price=0):
        """Submits a new spot-instance request.

        Submits a new spot-instance request using the configuration information given to
        the constructor, and an updated price.

        :param recent_price: a recent price that was not fulfilled (default: 0).
        :return: the submitted request.
        """
        while True:
            price = self._get_price(recent_price)
            try:
                request = self._conn.request_spot_instances(
                    price, type='one-time',
                    image_id=self._config['ami_id'], key_name=self._config['key_pair_name'],
                    security_groups=self._config['security_groups'],
                    instance_type=self._config['instance_type'])
                request = request[0] if request else None
                if request:
                    self._log.write('submitted request: {0}, price={1}, state={2}'
                                    .format(request.id, price, request.state))
                return request
            except EC2ResponseError:
                # can occur when the bid is too low.
                traceback.print_exc(file=self._log.file())
                recent_price = price

    def _bucket_requests(self):
        """Returns spot-instance requests bucketed by Request.State.

        Returns a dict where keys are Request.State values, and each value is a list
        of Request objects (which might be empty).

        :return: dict
        """
        requests = {
            Request.State.Dead: [],
            Request.State.Terminated: [],
            Request.State.Pending: [],
            Request.State.Holding: [],
            Request.State.Fulfilled: [],
            Request.State.Marked: []
        }

        spots = self._conn.get_all_spot_instance_requests()
        for req in [Request(r) for r in spots]:
            requests[req.state()].append(req)
            if req.state() not in (Request.State.Dead, Request.State.Terminated):
                self._log.write('request {0}: state={1}, status={2}, price={3}'
                                .format(req.req.id, req.req.state, req.req.status.code, req.req.price))

        self._log.write('dead: {0} / terminated: {1} / pending: {2} / holding: {3} / fulfilled: {4}'
                        .format(len(requests[Request.State.Dead]),
                                len(requests[Request.State.Terminated]),
                                len(requests[Request.State.Pending]),
                                len(requests[Request.State.Holding]),
                                len(requests[Request.State.Fulfilled])
        ))

        return requests

    def _get_price(self, recent_price=0):
        """Suggests a new spot-instance bid price.

        Uses the price-strategy supplied to the constructor, and an optional recent price,
        to select and suggest a new spot-instance bid price. Pricing intends for requests
        to be fulfilled, but may take a few iterations. The 'high' and 'average-high'
        price strategies should have the best chance of fulfillment.

        :param recent_price: a recent bid price that was not fulfilled (default: 0).
        :return: suggested bid price.
        """
        low, high, avg = self.get_price_info()
        factor = 1.05
        strategy = self._config['price_strategy']
        if strategy == 'high':
            price = max(high, recent_price*factor)
        elif strategy == 'random':
            l = max(low, recent_price*factor)
            h = max(high, recent_price*factor)
            price = l + abs(h-l)*random.random()
        elif strategy == 'average-high':
            a = max(avg, recent_price*factor)
            price = a + abs(high-a)/2
        else:
            # strategy == 'average'
            price = max(avg, recent_price*factor)

        self._log.write('price: {price}; recent: {recent_price}, (l,a,h)={low}, {avg}, {high} ({strategy})'
                        .format(**locals()))
        return price

    def _get_active_instances(self):
        """Returns a list of EC2 instances created via a spot-instance request.

        The returned list of instances all have an associated spot_instance_request_id, and
        are not in the 'terminated' or 'shutting-down' state.

        :return: list of instances (may be empty).
        """
        result = self._conn.get_all_instances()
        lst = []
        for reservation in result:
            for instance in reservation.instances:
                if instance.state not in ('terminated', 'shutting-down') and\
                   instance.spot_instance_request_id:
                    lst.append(instance)
        return lst

    def _get_single_instance(self, id):
        """Returns a single EC2 instance.

        Convenience method.

        :param id: specifies the instance ID.
        :return: the instance object, or None.
        """
        r = self._conn.get_all_instances(id)
        return r[0].instances[0] if r and r[0].instances else None
