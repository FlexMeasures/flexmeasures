Dependency Management
=======================

Requirements
-------------

FlexMeasures is built on the shoulder of giants, namely other open source libraries.
Look into the `requirements` folder to see what is required to run FlexMeasures (`app.in`) or to test it, or to build this documentation.

The `.in` files specify our general demands, and in `.txt` files, we keep a set of pinned dependency versions, so we can all work on the same background (crucial to compare behavior of installations to each other).

To install these pinned requirements, run:

.. code-block:: bash

    $ make install-for-dev

Check out `Makefile` for other useful commands, but this should get you going.

To upgrade the pinned versions, we can run:


.. code-block:: bash

    $ make upgrade-deps


Python versions
----------------

In addition, we support a range of Python versions (as you can see in the `requirements` folder.

Now ― you probably have only one Python version installed. Let's say you add a dependency, or update the minimum required version. How to update the pinned sets of requirements across all Python versions?

.. code-block:: bash

    $ cd ci; ./update-packages.sh; cd ../

This script will use docker to do these upgrades per Python version.

Still, we'd also like to be able to test FlexMeasures across all these versions.
We've added that capability to our CI pipeline (GitHub Actions), so you could clone it an make a PR, in order to run them.

