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

FlexMeasures provides the `POST /api/v2_0/requestAuthToken <../api/v2_0.html#post--api-v2_0-requestAuthToken>`_ endpoint, as discussed in :ref:`api_auth`. 
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

It only expects you to set ``email`` and ``password`` somewhere (you could also pass them in). In addition, we expect here that ``flexmeasures_domain`` is set to the FlexMeasures server you interact with, for example "https://company.flexmeasures.io". 

We'll see how to make use of the ``getAuthToken`` function right away, keep on reading.




Load user information
-----------------------

Let's say we are interested in a particular user's meta data. For instance, which email address do they have and which timezone are they operating in? 

Here is some code to find out and display that information in a simple HTML table:


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

.. image:: https://github.com/SeitaBV/screenshots/raw/main/tut/user_info.png
    :align: center
..    :scale: 40%


From FlexMeasures, we are using the `GET /api/v2_0/user <../api/v2_0.html#get--api-v2_0-user-(id)>`_ endpoint, which loads information about one user.
Browse its documentation to learn about other information you could get.


Load asset information
-----------------------

Similarly, we can load asset information. Say we have a user ID and we want to show which assets FlexMeasures administrates for that user.


.. code-block:: html

    <table id="assetTable">
        <thead>
          <tr>
            <th>Asset name</th>
            <th>Type</th>
            <th>Capacity</th>
          </tr>
        </thead>
        <tbody></tbody>
    </table>


.. code-block:: JavaScript
    
    function loadAssets(userId, authToken) {
        var params = new URLSearchParams();
        params.append("owner_id", userId);
        fetch(flexmeasures_domain + '/api/v2_0/assets?' + params.toString(),
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
            tr.innerHTML = `<td>${row.display_name}</td><td>${row.asset_type_name}</td><td>${row.capacity_in_mw} MW</td>`;
            tbody.appendChild(tr);
            });
        })            
    }

    document.onreadystatechange = () => {
        if (document.readyState === 'complete') {
            getAuthToken()
            .then(function(response) {
                var authToken = response.auth_token;
                loadAssets(userId, authToken);
            })
        }
    }

           
The result looks like this in your browser:

.. image:: https://github.com/SeitaBV/screenshots/raw/main/tut/asset_info.png
    :align: center
..    :scale: 40%


 
From FlexMeasures, we are using the `GET /api/v2_0/assets <../api/v2_0.html#get--api-v2_0-assets>`_ endpoint, which loads a list of assets. Note how, unlike the user endpoint above, we are passing a query parameter here (``owner_id``). We are only displaying a subset of the information which is available about assets. Browse the endpoint documentation to learn other information you could get.


Embedding plots
------------------------

Creating plots from data can consume lots of development time. FlexMeasures can help here by delivering ready-made plots.

In this tutorial, let's display two plots: one with power measurements and forecasts (a solar panel installation) and one with schedules of several EV chargers on the same location, next to each other for easy comparison.

First, we define two div tags for the two plots and a basic layout for them. We also load the Bokeh library, more about that below.

.. code-block:: html

    <style>
        #flexbox {
            display: flex;
        }
        #plot-div1, #plot-div2 {
            height: 450px;
            width: 450px;
            border: 1px solid grey;
        }
        /* a fix we have to do if we position absolutely-positioned Bokeh plots in a flexbox design */
        .bk-plot-layout, .bk-plot-wrapper {
            position: relative !important;
        }
    </style>

.. code-block:: html
    
    <script src="https://cdn.pydata.org/bokeh/release/bokeh-1.0.4.min.js"></script>
    <div id="flexbox">
        <div id="plot-div1"></div>
        <div id="plot-div2"></div>
    </div>

Now we define a JavaScript function to ask the FlexMeasures API for a plot:

.. code-block:: JavaScript

    function renderPlot(params, authToken, divId){
        fetch(flexmeasures_domain + '/api/v2_0/charts/power?' + params.toString(),
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
        .then(function(response) { return response.json(); })
        .then(function(item) { Bokeh.embed.embed_item(item, divId); })
        .then(console.log("Got plot specifications from server and rendered it ..."))
    }

This function allows us to request a plot (actually, HTML and JavaScript code to render a plot), and then render the plot within a ``div`` tag of our choice.

As FlexMeasures uses `the Bokeh Visualization Library <https://bokeh.org/>`_ internally, we also need to import the Bokeh client library to render the plots (see the ``script`` tag above). It's crucial to note that FlexMeasures is not transferring images across HTTP here, just information needed to render them.

.. note:: The Bokeh library version you use in your frontend needs to match the version which FlexMeasures uses internally, check ``requirements/app.txt`` when in doubt.

Now let's call this function when the HTML page is opened, to load our two plots:

.. code-block:: JavaScript

    document.onreadystatechange = () => {
        if (document.readyState === 'complete') {
            getAuthToken()
            .then(function(response) {
                var authToken = response.auth_token;

                var urlData1 = new URLSearchParams();
                urlData1.append("resource", "ss_pv");
                urlData1.append("start_time", "2015-06-01T10:00:00");
                urlData1.append("end_time", "2015-06-03T10:00:00");
                urlData1.append("resolution", "PT15M");
                urlData1.append("forecast_horizon", "PT6H");
                urlData1.append("show_individual_traces_for", "none");
                renderPlot(urlData1, authToken, "plot-div1");
                
                var urlData2 = new URLSearchParams();
                urlData2.append("resource", "Test station (Charge Point)");
                urlData2.append("start_time", "2015-01-01T00:00:00");
                urlData2.append("end_time", "2015-01-01T03:00:00");
                urlData2.append("resolution", "PT15M");
                urlData2.append("show_individual_traces_for", "schedules");
                renderPlot(urlData2, authToken, "plot-div2");
            })
        }
    }

For each of the two plots we request, we pass in several query parameters to describe what we want to see. We define which asset and what time range, which resolution and forecasting horizon.
Note the ``show_individual_traces_for`` setting - it allows us to split data from individual assets (usually measurements, forecasts and schedules are visually aggregated in FlexMeasure's power plots, see :ref:`analytics` for example).

           
The result looks like this in your browser:

.. image:: https://github.com/SeitaBV/screenshots/raw/main/tut/plots.png
    :align: center
..    :scale: 40%


From FlexMeasures, we are using the `GET /api/v2_0/charts/power <../api/v2_0.html#get--api-v2_0-charts-power>`_ endpoint, which loads HTML and JavaScript. 
Browse the endpoint documentation to learn more about it.