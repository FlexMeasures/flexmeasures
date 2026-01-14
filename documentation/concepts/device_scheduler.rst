.. _storage_device_scheduler:

Storage device scheduler: Linear model
=======================================

Introduction
--------------
This generic storage device scheduler is able to handle an EMS with multiple devices, with various types of constraints on the EMS level and on the device level,
and with multiple market commitments on the EMS level.

A typical example is a house with many devices. The commitments are assumed to be with regard to the flow of energy to the device (positive for consumption, negative for production). In practice, this generic scheduler is used in the **StorageScheduler** to schedule a storage device.
    
The solver minimizes the costs of deviating from the commitments.



Notation
---------

Indexes
^^^^^^^^
================================ ================================================ ==============================================================================================================  
Symbol                              Variable in the Code                           Description
================================ ================================================ ==============================================================================================================  
:math:`c`                             c                                                  Commitments, for example, day-ahead or intra-day market commitments.
:math:`d`                             d                                                  Devices, for example, a battery or a load.
:math:`j`                             j                                                  0-indexed time dimension. 
================================ ================================================ ==============================================================================================================  

.. note::
  The time index :math:`j` has two interpretations: a time period or an instantaneous moment at the end of time period :math:`j`. 
  For example, :math:`j` in flow constraints correspond to time periods, whereas :math:`j` used in a stock constraint refers to the end of time period :math:`j`.

Parameters
^^^^^^^^^^
================================ ================================================ ==============================================================================================================  
Symbol                              Variable in the Code                           Description
================================ ================================================ ==============================================================================================================  
:math:`Price_{up}(c,j)`               up_price                                           Price of incurring an upwards deviations in commitment :math:`c` during time period :math:`j`.
:math:`Price_{down}(c,j)`             down_price                                         Price of incurring a downwards deviations in commitment :math:`c` during time period :math:`j`.
:math:`\eta_{up}(d,j)`                device_derivative_up_efficiency                    Upwards conversion efficiency.
:math:`\eta_{down}(d,j)`              device_derivative_down_efficiency                  Downwards conversion efficiency.
:math:`Stock_{min}(d,j)`              device_min                                         Minimum quantity for the stock of device :math:`d` at the end of time period :math:`j`.
:math:`Stock_{max}(d,j)`              device_max                                         Maximum quantity for the stock of device :math:`d` at the end of time period :math:`j`.
:math:`\epsilon(d,j)`                 efficiencies                                       Stock energy losses.
:math:`P_{max}(d,j)`                  device_derivative_max                              Maximum flow of device :math:`d` during time period :math:`j`.
:math:`P_{min}(d,j)`                  device_derivative_min                              Minimum flow of device :math:`d` during time period :math:`j`.
:math:`P^{ems}_{min}(j)`              ems_derivative_min                                 Minimum flow of the EMS during time period :math:`j`.
:math:`P^{ems}_{max}(j)`              ems_derivative_max                                 Maximum flow of the EMS during time period :math:`j`.
:math:`Commitment(c,j)`               commitment_quantity                                Commitment c (at EMS level) over time step :math:`j`.
:math:`M`                             M                                                  Large constant number, upper bound of :math:`Power_{up}(d,j)` and :math:`|Power_{down}(d,j)|`.
:math:`D(d,j)`                        stock_delta                                        Explicit energy gain or loss of device :math:`d` during time period :math:`j`.
================================ ================================================ ==============================================================================================================  


Variables
^^^^^^^^^
================================ ================================================ ==============================================================================================================  
Symbol                              Variable in the Code                           Description
================================ ================================================ ==============================================================================================================  
:math:`\Delta_{up}(c,j)`              commitment_upwards_deviation                       Upwards deviation from the power commitment :math:`c` of the EMS during time period :math:`j`.
:math:`\Delta_{down}(c,j)`            commitment_downwards_deviation                     Downwards deviation from the power commitment :math:`c` of the EMS during time period :math:`j`.
:math:`\Delta Stock(d,j)`                           n/a                                  Change of stock of device :math:`d` at the end of time period :math:`j`.
:math:`P_{up}(d,j)`                   device_power_up                                    Upwards power of device :math:`d` during time period :math:`j`.
:math:`P_{down}(d,j)`                 device_power_down                                  Downwards power of device :math:`d` during time period :math:`j`.
:math:`P^{ems}(j)`                    ems_power                                          Aggregated power of all the devices during time period :math:`j`.
:math:`\sigma(d,j)`                   device_power_sign                                  Upwards power activation if :math:`\sigma(d,j)=1`, downwards power activation otherwise.
================================ ================================================ ==============================================================================================================  

Cost function
--------------

The cost function quantifies the total cost of upwards and downwards deviations from the different commitments.

.. math:: 
    :name: cost_function

    \min [\sum_{c,j} \Delta_{up}(c,j) \cdot Price_{up}(c,j) +  \Delta_{down}(c,j) \cdot Price_{down}(c,j)]


State dynamics
---------------

To simplify the description of the model, the auxiliary variable :math:`\Delta Stock(d,j)` is introduced in the documentation. It represents the
change of :math:`Stock(d,j)`, taking into account conversion efficiencies but not considering the storage losses.

.. math::
  :name: stock

    \Delta Stock(d,j) = \frac{P_{down}(d,j)}{\eta_{down}(d,j) } + P_{up}(d,j)  \cdot \eta_{up}(d,j) + D(d,j)


.. math:: 
  :name: device_bounds

    Stock_{min}(d,j)  \leq Stock(d,j) - Stock(d,-1)\leq Stock_{max}(d,j) 


Perfect efficiency
^^^^^^^^^^^^^^^^^^^

.. math:: 
  :name: efficiency_e1

    Stock(d, j) = Stock(d, j-1) + \Delta Stock(d,j)

Left efficiency
^^^^^^^^^^^^^^^^^
First apply the stock change, then apply the losses (i.e. the stock changes on the left side of the time interval in which the losses apply)


.. math:: 
  :name: efficiency_left

    Stock(d, j)  = (Stock(d, j-1) + \Delta Stock(d,j)) \cdot \epsilon(d,j)


Right efficiency
^^^^^^^^^^^^^^^^^
First apply the losses, then apply the stock change (i.e. the stock changes on the right side of the time interval in which the losses apply)

.. math:: 
  :name: efficiency_right

    Stock(d, j)  = Stock(d, j-1) \cdot \epsilon(d,j) + \Delta Stock(d,j)

Linear efficiency
^^^^^^^^^^^^^^^^^
Assume the change happens at a constant rate, leading to a linear stock change, and exponential decay, within the current interval

.. math:: 
  :name: efficiency_linear

    Stock(d, j)  = Stock(d, j-1) \cdot \epsilon(d,j) + \Delta Stock(d,j) \cdot \frac{\epsilon(d,j) - 1}{log(\epsilon(d,j))}

Constraints
--------------

Device bounds
^^^^^^^^^^^^^

.. math:: 
  :name: device_derivative_bounds

    P_{min}(d,j) \leq P_{up}(d,j) + P_{down}(d,j)\leq P_{max}(d,j)

.. math:: 
  :name: device_down_derivative_bounds

    min(P_{min}(d,j),0) \leq P_{down}(d,j)\leq 0


.. math:: 
  :name: device_up_derivative_bounds

    0 \leq P_{up}(d,j)\leq max(P_{max}(d,j),0)


Upwards/Downwards activation selection
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Avoid simultaneous upwards and downwards activation during the same time period.

.. math:: 
  :name: device_up_derivative_sign

    P_{up}(d,j) \leq M \cdot \sigma(d,j)

.. math:: 
  :name: device_down_derivative_sign

    -P_{down}(d,j) \leq M \cdot (1-\sigma(d,j))


Grid constraints
^^^^^^^^^^^^^^^^^

.. math:: 
    :name: device_derivative_equalities

    P^{ems}(d,j) = P_{up}(d,j) + P_{down}(d,j)

.. math:: 
  :name: ems_derivative_bounds

    P^{ems}_{min}(j) \leq \sum_d P^{ems}(d,j) \leq P^{ems}_{max}(j)

Power coupling constraints
^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. math:: 
    :name: ems_flow_commitment_equalities

    \sum_d P^{ems}(d,j) = \sum_c Commitment(c,j) + \Delta_{up}(c,j) + \Delta_{down}(c,j)

