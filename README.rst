Base HTTP Client
================

.. image:: https://img.shields.io/pypi/v/base-http-client.svg
   :target: https://pypi.python.org/pypi/base-http-client/
   :alt: Latest Version

.. image:: https://img.shields.io/pypi/wheel/base-http-client.svg
   :target: https://pypi.python.org/pypi/base-http-client/

.. image:: https://img.shields.io/pypi/pyversions/base-http-client.svg
   :target: https://pypi.python.org/pypi/base-http-client/

.. image:: https://img.shields.io/pypi/l/base-http-client.svg
   :target: https://pypi.python.org/pypi/base-http-client/

Base HTTP client for your integrations based on aiohttp_.

Installation
------------

Installation is possible in standard ways, such as PyPI or
installation from a git repository directly.

Installing from PyPI_:

.. code-block:: bash

   pip3 install base-http-client

Installing from github.com:

.. code-block:: bash

   pip3 install git+https://github.clm/andy-takker/base_http_client

The package contains several extras and you can install additional dependencies
if you specify them in this way.

For example, with msgspec_:

.. code-block:: bash

   pip3 install "base-http-client[msgspec]"

Complete table of extras below:

+-----------------------------------------------+----------------------------------+
| example                                       | description                      |
+===============================================+==================================+
| ``pip3 install "base-http-client[msgspec]"``  | For using msgspec_ structs       |
+-----------------------------------------------+----------------------------------+
| ``pip3 install "base-http-client[orjson]"``   | For fast parsing json by orjson_ |
+-----------------------------------------------+----------------------------------+
| ``pip3 install "base-http-client[pydantic]"`` | For using pydantic_ models       |
+-----------------------------------------------+----------------------------------+

Using
~~~~~




.. _PyPI: https://pypi.org/
.. _aiohttp: https://pypi.org/project/aiohttp/
.. _msgspec: https://github.com/jcrist/msgspec
.. _orjson: https://github.com/ijl/orjson
.. _pydantic: https://github.com/pydantic/pydantic