
.. _redis-queue:

Redis Queues
=============================

Requirements
-------------

The hard computation work (e.g. forecasting, scheduling) should happen outside of web requests (asynchronously), in job queues accessed by worker processes.

This queueing relies on a Redis server, which has to be installed locally, or used on a separate host. In the latter case, configure :ref:`redis-config` details in your FlexMeasures config file.

Here we assume you have access to a Redis server and configured it (see :ref:`redis-config`).
The FlexMeasures unit tests use fakeredis to simulate this task queueing, with no configuration required.

.. note:: See also :ref:`docker-compose` for usage of Redis via Docker and a more hands-on tutorial on the queues.


Run workers
-------------

Here is how to run one worker for each kind of job (in separate terminals):

.. code-block:: bash

   $ flexmeasures jobs run-worker --name our-only-worker --queue forecasting|scheduling

Running multiple workers in parallel might be a great idea.

.. code-block:: bash

   $ flexmeasures jobs run-worker --name forecaster --queue forecasting
   $ flexmeasures jobs run-worker --name scheduler --queue scheduling

You can also clear the job queues:

.. code-block:: bash

   $ flexmeasures jobs clear-queue --queue forecasting
   $ flexmeasures jobs clear-queue --queue scheduling


When the main FlexMeasures process runs (e.g. by ``flexmeasures run``\ ), the queues of forecasting and scheduling jobs can be visited at ``http://localhost:5000/tasks/forecasting`` and ``http://localhost:5000/tasks/schedules``\ , respectively (by admins).



Inspect the queue and jobs
------------------------------

The first option to inspect the state of the ``forecasting`` queue should be via the formidable `RQ dashboard <https://github.com/Parallels/rq-dashboard>`_. If you have admin rights, you can access it at ``your-flexmeasures-url/rq/``\ , so for instance ``http://localhost:5000/rq/``. You can also start RQ dashboard yourself (but you need to know the redis server credentials):

.. code-block:: bash

   $ pip install rq-dashboard
   $ rq-dashboard --redis-host my.ip.addr.ess --redis-password secret --redis-database 0


RQ dashboard shows you ongoing and failed jobs, and you can see the error messages of the latter, which is very useful.

Finally, you can also inspect the queue and jobs via a console (\ `see the nice RQ documentation <http://python-rq.org/docs/>`_\ ), which is more powerful. Here is an example of inspecting the finished jobs and their results:

.. code-block:: python

   from redis import Redis
   from rq import Queue
   from rq.job import Job
   from rq.registry import FinishedJobRegistry

   r = Redis("my.ip.addr.ess", port=6379, password="secret", db=2)
   q = Queue("forecasting", connection=r)
   finished = FinishedJobRegistry(queue=q)

   finished_job_ids = finished.get_job_ids()
   print("%d jobs finished successfully." % len(finished_job_ids))

   job1 = Job.fetch(finished_job_ids[0], connection=r)
   print("Result of job %s: %s" % (job1.id, job1.result))


Redis queues on Windows
---------------------------

On Unix, the rq system is automatically set up as part of FlexMeasures's main setup (the ``rq`` dependency).

However, rq is `not functional on Windows <http://python-rq.org/docs>`_ without the Windows Subsystem for Linux.

On these versions of Windows, FlexMeasures's queuing system uses an extension of Redis Queue called ``rq-win``.
This is also an automatically installed dependency of FlexMeasures.

However, the Redis server needs to be set up separately. Redis itself does not work on Windows, so it might be easiest to commission a Redis server in the cloud (e.g. on kamatera.com).

If you want to install Redis on Windows itself, it can be set up on a virtual machine as follows:


* `Install Vagrant on Windows <https://www.vagrantup.com/intro/getting-started/>`_ and `VirtualBox <https://www.virtualbox.org/>`_
* Download the `vagrant-redis <https://raw.github.com/ServiceStack/redis-windows/master/downloads/vagrant-redis.zip>`_ vagrant configuration
* Extract ``vagrant-redis.zip`` in any folder, e.g. in ``c:\vagrant-redis``
* Set ``config.vm.box = "hashicorp/precise64"`` in the Vagrantfile, and remove the line with ``config.vm.box_url``
* Run ``vagrant up`` in Command Prompt
* In case ``vagrant up`` fails because VT-x is not available, `enable it <https://www.howali.com/2017/05/enable-disable-intel-virtualization-technology-in-bios-uefi.html>`_ in your bios `if you can <https://www.intel.com/content/www/us/en/support/articles/000005486/processors.html>`_ (more debugging tips `here <https://forums.virtualbox.org/viewtopic.php?t=92111>`_ if needed)
