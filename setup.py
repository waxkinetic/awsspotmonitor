from __future__ import absolute_import

from setuptools import setup, find_packages

readme = open('README.md').read()

setup(
    name='awsspotmonitor',
    version='0.01-dev',
    url='http://github.com/waxkinetic/awsspotmonitor',
    license='BSD',

    author='Rick Bohrer',
    author_email='waxkinetic@gmail.com',

    description='Simple AWS spot-instance monitoring and management.',
    long_description=readme,

    zip_safe=False,
    include_package_data=True,

    packages=find_packages(),

    setup_requires=[
        'setuptools-git >= 1.0b1'
    ],

    install_requires=[
        'boto >= 2.8.0'
    ]
)
