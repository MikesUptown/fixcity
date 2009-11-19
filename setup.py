from setuptools import setup, find_packages

version='0.1dev'

install_requires=[
      'geopy==dev,>=0.93dev-r84',
      'sorl-thumbnail>=3.2.2',
      'Django>=1.1.1',
      'django-registration>=0.7',
      'psycopg2>=2.0.12',
      'PIL==1.1.6',
      'wsgilog>=0.1',
      'httplib2',
      'poster',
      'mock',
      'tweepy',
      ]

import sys
if sys.version_info[:2] < (2, 6):
    install_requires.append('ctypes>=1.0.2')

setup(name='fixcity',
      version=version,
      description="Build me a bike rack!",
      author="Ivan Willig, Paul Winkler, Sonali Sridhar, Andy Cochran, etc.",
      author_email="iwillig@opengeo.org",
      url="http://www.plope.com/software/ExternalEditor",
      zip_safe=False,
      scripts=[],
      packages=find_packages(),
      dependency_links=[
        'http://geopy.googlecode.com/svn/branches/reverse-geocode#egg=geopy-dev',
        'http://dist.repoze.org/PIL-1.1.6.tar.gz#egg=PIL-1.1.6',
        'http://sourceforge.net/projects/ctypes/files/ctypes/1.0.2/ctypes-1.0.2.tar.gz/download#egg=ctypes-1.0.2',
        'https://svn.openplans.org/eggs/httplib2-0.4.0.zip',
        ],
      install_requires=install_requires,
      )
