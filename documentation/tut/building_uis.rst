.. _tut_building_uis:

Building custom UIs
========================

FlexMeasures provides its own UI (see :ref:`dashboard`), but it is a back office platform first.
Most energy service companies already have their own user-facing system.
We therefore made it possible to incorporate information from FlexMeasures in custom UIs.

This tutorial will show how the FlexMeasures API can be used from JavaScript to extract information and display it in a browser (using HTML). We'll extract information about users, assets and even whole plots!

.. contents:: Table of contents
    :local:
    :depth: 1


.. note:: We'll use standard JavaScript for this tutorial, in particular the `fetch <https://developer.mozilla.org/en-US/docs/Web/API/Fetch_API/Using_Fetch>`_ functionality, which many browsers support out-of-the-box these days. You might want to use more high-level frameworks like jQuery, Angular, React or VueJS for your frontend, of course.


Get an authentication token
-----------------------

FlexMeasures provides the `[POST] /api/requestAuthToken <../api/v2_0.html#post--api-v2_0-requestAuthToken>`_ endpoint, as discussed in :ref:`api_auth`.
Here is a JavaScript function to call it:

.. code-block:: JavaScript

    var flexmeasures_domain =  "http://localhost:5000";    
    
    function getAuthToken(){
        return fetch(flexmeasures_domain + '/api/requestAuthToken',
            {
                method: "POST",
                mode: "cors", 
                headers:
                {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({"email": email, "password": password})  
            }
            )
            .then(function(response) { return response.json(); })
            .then(console.log("Got auth token from FlexMeasures server ..."));
    }

It only expects you to set ``email`` and ``password`` somewhere (you could also pass them to the function, your call). In addition, we expect here that ``flexmeasures_domain`` is set to the FlexMeasures server you interact with, for example "https://company.flexmeasures.io". 

We'll see how to make use of the ``getAuthToken`` function right away, keep on reading.




Load user information
-----------------------

Let's say we are interested in a particular user's meta data. For instance, which email address do they have and which timezone are they operating in? 

Given we have set a variable called ``userId``, here is some code to find out and display that information in a simple HTML table:


.. code-block:: html

    <h1>User info</h1>
    <p>
        Email address: <span id="user_email"></span>
    </p>
    <p>
        Time zone: <span id="user_timezone"></span>
    </p>

.. code-block:: JavaScript

    function loadUserInfo(userId, authToken) {
        fetch(flexmeasures_domain + '/api/v2_0/user/' + userId,
            {
                method: "GET",
                mode: "cors",
                headers:
                    {
                    "Content-Type": "application/json",
                    "Authorization": authToken
                    },
            }
        )
        .then(console.log("Got user data from FlexMeasures server ..."))
        .then(function(response) { return response.json(); })
        .then(function(userInfo) {
            document.querySelector('#user_email').innerHTML = userInfo.email;
            document.querySelector('#user_timezone').innerHTML = userInfo.timezone;
        })            
    }

    document.onreadystatechange = () => {
        if (document.readyState === 'complete') {
            getAuthToken()
            .then(function(response) {
                var authToken = response.auth_token;
                loadUserInfo(userId, authToken);
            })
        }
    }
           
The result looks like this in your browser:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/user_info.png
    :align: center
..    :scale: 40%


From FlexMeasures, we are using the `[GET] /user <../api/v3_0.html#get--api-v3_0-user-(id)>`_ endpoint, which loads information about one user.
Browse its documentation to learn about other information you could get.


Load asset information
-----------------------

Similarly, we can load asset information. Say we have a variable ``accountId`` and we want to show which assets FlexMeasures administrates for that account.

For the example below, we've used the ID of the account from our toy tutorial, see :ref:`toy tutorial<tut_toy_schedule>`.


.. code-block:: html

    <style>
        #assetTable th, #assetTable td {
            border-right: 1px solid gray;
            padding-left: 5px;
            padding-right: 5px;
        }
    </style>

.. code-block:: html

    <table id="assetTable">
        <thead>
          <tr>
            <th>Asset name</th>
            <th>ID</th>
            <th>Latitude</th>
            <th>Longitude</th>
          </tr>
        </thead>
        <tbody></tbody>
    </table>


.. code-block:: JavaScript
    
    function loadAssets(accountId, authToken) {
        var params = new URLSearchParams();
        params.append("account_id", accountId);
        fetch(flexmeasures_domain + '/api/v3_0/assets?' + params.toString(),
            {
                method: "GET",
                mode: "cors",
                headers:
                    {
                    "Content-Type": "application/json",
                    "Authorization": authToken
                    },
            }
        )
        .then(console.log("Got asset data from FlexMeasures server ..."))
        .then(function(response) { return response.json(); })
        .then(function(rows) {
            rows.forEach(row => {
            const tbody = document.querySelector('#assetTable tbody');
            const tr = document.createElement('tr');
            tr.innerHTML = `<td>${row.name}</td><td>${row.id}</td><td>${row.latitude}</td><td>${row.longitude}</td>`;
            tbody.appendChild(tr);
            });
        })            
    }

    document.onreadystatechange = () => {
        if (document.readyState === 'complete') {
            getAuthToken()
            .then(function(response) {
                var authToken = response.auth_token;
                loadAssets(accountId, authToken);
            })
        }
    }

           
The result looks like this in your browser:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/asset_info.png
    :align: center
..    :scale: 40%


 
From FlexMeasures, we are using the `[GET] /assets <../api/v3_0.html#get--api-v3_0-assets>`_ endpoint, which loads a list of assets.
Note how, unlike the user endpoint above, we are passing a query parameter to the API (``account_id``).
We are only displaying a subset of the information which is available about assets.
Browse the endpoint documentation to learn other information you could get.

For a listing of public assets, replace `/api/v3_0/assets` with `/api/v3_0/assets/public`.


Embedding charts
------------------------

Creating charts from data can consume lots of development time.
FlexMeasures can help here by delivering ready-made charts.
In this tutorial, we'll embed a chart with electricity prices.

First, we define a div tag for the chart and a basic layout (full width). We also load the visualization libraries we need (more about that below), and set up a custom formatter we use in FlexMeasures charts.

.. code-block:: html

    <script src="https://d3js.org/d3.v6.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega@5.22.1"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-lite@5.2.0"></script>
    <script src="https://cdn.jsdelivr.net/npm/vega-embed@6.20.8"></script>
    <script>
        vega.expressionFunction('quantityWithUnitFormat', function(datum, params) {
            return d3.format(params[0])(datum) + " " + params[1];
        });
    </script>

    <div id="sensor-chart" style="width: 100%;"></div>

Now we define a JavaScript function to ask the FlexMeasures API for a chart and then embed it:

.. code-block:: JavaScript

    function embedChart(params, authToken, sensorId, divId){
        fetch(
            flexmeasures_domain + '/api/dev/sensor/' + sensorId + '/chart?include_data=true&' + params.toString(),
            {
                method: "GET",
                mode: "cors",
                headers:
                    {
                    "Content-Type": "application/json",
                    "Authorization": authToken
                    }
            }
        )
        .then(function(response) {return response.json();})
        .then(function(data) {vegaEmbed(divId, data)})
    }

This function allows us to request a chart (actually, a JSON specification of a chart that can be interpreted by vega-lite), and then embed it within a ``div`` tag of our choice.

From FlexMeasures, we are using the `GET /api/dev/sensor/(id)/chart/ <../api/dev.html#get--api-dev-sensor-(id)-chart->`_ endpoint.
Browse the endpoint documentation to learn more about it.

.. note:: Endpoints in the developer API are still under development and are subject to change in new releases.

Here are some common parameter choices for our JavaScript function:

.. code-block:: JavaScript

    var params = new URLSearchParams();
    params.append("width", 400); // an integer number of pixels; without it, the chart will be scaled to the full width of the container (note that we set the div width to 100%)
    params.append("height", 400); // an integer number of pixels; without it, a FlexMeasures default is used
    params.append("event_starts_after", '2022-10-01T00:00+01'); // only fetch events from midnight October 1st
    params.append("event_ends_before", '2022-10-08T00:00+01'); // only fetch events until midnight October 8th
    params.append("beliefs_before", '2022-10-03T00:00+01'); // only fetch beliefs prior to October 3rd (time travel)


As FlexMeasures uses `the Vega-Lite Grammar of Interactive Graphics <https://vega.github.io/vega-lite/>`_ internally, we also need to import this library to render the chart (see the ``script`` tags above). It's crucial to note that FlexMeasures is not transferring images across HTTP here, just information needed to render them.

.. note:: It's best to match the visualization library versions you use in your frontend to those used by FlexMeasures. These are set by the FLEXMEASURES_JS_VERSIONS config (see :ref:`configuration`) with defaults kept in ``flexmeasures/utils/config_defaults``.

Now let's call this function when the HTML page is opened, to embed our chart:

.. code-block:: JavaScript

    document.onreadystatechange = () => {
        if (document.readyState === 'complete') {
            getAuthToken()
            .then(function(response) {
                var authToken = response.auth_token;

                var params = new URLSearchParams();
                params.append("event_starts_after", '2022-01-01T00:00+01');
                embedChart(params, authToken, 1, '#sensor-chart');
            })
        }
    }

The parameters we pass in describe what we want to see: all data for sensor 3 since 2022.
If you followed our :ref:`toy tutorial<tut_toy_schedule>` on a fresh FlexMeasures installation, sensor 1 contains market prices (authenticate with the toy-user to gain access).

           
The result looks like this in your browser:

.. image:: https://github.com/FlexMeasures/screenshots/raw/main/tut/plotting-prices.png
    :align: center
..    :scale: 40%
