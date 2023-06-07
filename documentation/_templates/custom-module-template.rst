.. Adapted from https://stackoverflow.com/a/62613202
{{ fullname | escape | underline}}

{% block modules %}
{% if modules %}
.. rubric:: Modules

.. autosummary::
   :toctree:
   :template: custom-module-template.rst                
   :recursive:
{% for item in modules %}
   {% if "test" not in item %}
   {{ item }}
   {% endif %}
{%- endfor %}
{% endif %}
{% endblock %}

.. automodule:: {{ fullname }}
  
   {% block attributes %}
   {% if attributes %}
   .. rubric:: Module Attributes


   {% for item in attributes %}
   .. autoattribute::
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block functions %}
   {% if functions %}
   .. rubric:: {{ _('Functions') }}

   {% for item in functions %}
   .. autofunction::
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block classes %}
   {% if classes %}
   .. rubric:: {{ _('Classes') }}

   {% for item in classes %}     
   .. autoclass:: {{ item }}
      :members:
      :special-members: __init__
      :private-members:
   {%- endfor %}
   {% endif %}
   {% endblock %}

   {% block exceptions %}
   {% if exceptions %}
   .. rubric:: {{ _('Exceptions') }}
      
   {% for item in exceptions %}
   .. autoexception::
      {{ item }}
   {%- endfor %}
   {% endif %}
   {% endblock %}