$(document).ready(function () {
    ready();
});


$(window).resize(function () {
    $('body').css('padding-top', $("#navbar-fixed-top").height());
    $('.floatThead-container').css('top', $("#navbar-container").height() - $('#topnavbar').height());
    $('.floatThead-container').css('margin-top', $("#navbar-container").height() - $('#topnavbar').height());
});


$(window).scroll(function () {
    $('.floatThead-container').css('top', $("#navbar-container").height() - $('#topnavbar').height());
});


var offshoreOrdered = false;
var batteryOrdered = false;


function showMsg(msg) {
    $("#msgModal .modal-content").html(msg);
    $("#msgModal").modal("show");
}

function showImage(resource, action, value) {
    //    $("#expectedValueModal .modal-dialog .modal-content img").html("static/control-mock-imgs/" + resource + "-action" + action + "-" + value + "MW.png")
    document.getElementById('expected_value_mock').src = "ui/static/control-mock-imgs/value-" + resource + "-action" + action + "-" + value + "MW.png"
    load_images = document.getElementsByClassName('expected_load_mock')
    for (var i = 0; i < load_images.length; i++) {
        load_images[i].src = "ui/static/control-mock-imgs/load-" + resource + "-action" + action + "-" + value + "MW.png"
    }
}


function defaultImage(action) {
    load_images = document.getElementsByClassName('expected_load_mock reset_default')
    for (var i = 0; i < load_images.length; i++) {
        load_images[i].src = "ui/static/control-mock-imgs/load-action" + action + ".png"
    }
}


function ready() {

    console.log("ready...");


    // For custom hover effects that linger for some time

    $("i").hover(
        function () {
            $(this).addClass('over');
        },
        function () {
            $(this).delay(3000).queue(function (next) {
                $(this).removeClass('over');
                next();
            });
        }
    );


    // Table pagination

    $.extend(true, $.fn.dataTable.defaults, {
        "conditionalPaging": {
            style: 'fade',
            speed: 2000,
        },
        "searching": true,
        "ordering": true,
        "info": true,
        "order": [],
        "lengthMenu": [[5, 10, 25, 50, 100, -1], [5, 10, 25, 50, 100, "All"]],
        "pageLength": 10,  // initial page length
        "oLanguage": {
            "sLengthMenu": "Show _MENU_ records",
            "sSearch": "Filter records:",
            "sInfo": "Showing _START_ to _END_ out of _TOTAL_ records",
            "sInfoFiltered": "(filtered from _MAX_ total records)",
            "sInfoEmpty": "No records to show",
        },
        "columnDefs": [{
            "targets": 'no-sort',
            "orderable": false,
        }],
        "stateSave": true,
    });
    // just searching and ordering, no paging
    $('.paginate-without-paging').DataTable({
        "paging": false,
    });
    // searching, ordering and paging
    $('.paginate').DataTable();
    // set default page lengths
    $('.paginate-5').dataTable().api().page.len(5).draw();
    $('.paginate-10').dataTable().api().page.len(10).draw();


    // Sliders

    $('#control-action-setting-offshore')
        .ionRangeSlider({
            skin: "big",
            type: "single",
            grid: true,
            grid_snap: true,
            min: 0,
            max: 5,
            from_min: 2,
            from_max: 3,
            from_shadow: true,
            postfix: "MW",
            force_edges: true,
            onChange: function (settingData) {
                action = 1;
                if (offshoreOrdered) {
                    action = 2;
                }
                value = settingData.from;
                $("#control-expected-value-offshore").html(numberWithCommas(value * 35000));
                showImage("offshore", action, value);
            }
        });

    $('#control-action-setting-battery').ionRangeSlider({
        skin: "big",
        type: "single",
        grid: true,
        grid_snap: true,
        min: 0,
        max: 5,
        from_min: 1,
        from_max: 2,
        from_shadow: true,
        postfix: "MW",
        force_edges: true,
        onChange: function (settingData) {
            action = 1;
            if (offshoreOrdered) {
                action = 2;
            }
            value = settingData.from;
            $("#control-expected-value-battery").html(numberWithCommas(value * 10000));
            showImage("battery", action, value);
        }
    });


    // Hover behaviour

    $("#control-tr-offshore").mouseenter(function (data) {
        action = 1;
        if (offshoreOrdered) {
            action = 2;
        }
        var value = $("#control-action-setting-offshore").data("ionRangeSlider").old_from;
        showImage("offshore", action, value);
    }).mouseleave(function (data) {
        action = 1;
        if (offshoreOrdered) {
            action = 2;
        }
        defaultImage(action);
    });

    $("#control-tr-battery").mouseenter(function (data) {
        action = 1;
        if (offshoreOrdered) {
            action = 2;
        }
        var value = $("#control-action-setting-battery").data("ionRangeSlider").old_from;
        showImage("battery", action, value);
    }).mouseleave(function (data) {
        action = 1;
        if (offshoreOrdered) {
            action = 2;
        }
        defaultImage(action);
    });


    // Navbar behaviour

    $(document.body).css('padding-top', $('#topnavbar').height());
    $(window).resize(function () {
        $(document.body).css('padding-top', $('#topnavbar').height());
    });


    // Table behaviour

    $('table').floatThead({
        position: 'absolute',
        top: $('#topnavbar').height(),
        scrollContainer: true
    });

    $(document).on('change', '#user-list-options input[name="include_inactive"]', function () {
        //Users list inactive
        $(this).closest('form').submit();
    })


    // Security messages styling

    $('.flashes').addClass('alert alert-info');


    // Check button behaviour

    $("#control-check-expected-value-offshore").click(function (data) {
        var value = $("#control-action-setting-offshore").data("ionRangeSlider").old_from;
        showImage("offshore", 1, value);
        $("#expectedValueModal").modal("show");
    });

    $("#control-check-expected-value-battery").click(function (data) {
        var value = $("#control-action-setting-battery").data("ionRangeSlider").old_from;
        action = 1;
        if (offshoreOrdered) {
            action = 2;
        }
        showImage("battery", action, value);
        $("#expectedValueModal").modal("show");
    });


    // Order button behaviour

    $("#control-order-button-ev").click(function (data) {
        showMsg("This action is not supported in this mockup.");
    });

    $("#control-order-button-onshore").click(function (data) {
        showMsg("This action is not supported in this mockup.");
    });

    $("#control-order-button-offshore").click(function (data) {
        if (offshoreOrdered) {
            showMsg("This action is not supported in this mockup.");
        }
        var value = $("#control-action-setting-offshore").data("ionRangeSlider").old_from;
        console.log("Offshore was ordered for " + value + "MW!");
        if (value == 2) {
            showMsg("Your order of " + value + "MW offshore wind curtailment will be processed!");
            $("#control-tr-offshore").addClass("active");
            $("#control-offshore-volume").html("Ordered: <b>2MW</b>");
            $("#control-order-button-offshore").html('<span class="fa fa-minus" aria-hidden="true"></span> Cancel').removeClass("btn-success").addClass("btn-danger");
            $("#control-check-expected-value-offshore").hide();
            $("#total_load").html("4.4");
            $("#total_value").html("230,000");
            offshoreOrdered = true;
        }
        else {
            showMsg("In this mockup, only ordering 2MW of offshore wind is supported.");
        }
    });

    $("#control-order-button-battery").click(function (data) {
        if (batteryOrdered) {
            showMsg("This action is not supported in this mockup.");
        }
        else if (!offshoreOrdered) {
            showMsg("In this mockup, please first order 2MW of offshore wind.");
        } else {
            var value = $("#control-action-setting-battery").data("ionRangeSlider").old_from;
            console.log("Battery was ordered for " + value + "MW!");
            showMsg("Your order of " + value + "MW battery shifting will be processed!");
            $("#control-tr-battery").addClass("active");
            $("#control-order-button-battery").html('<span class="fa fa-minus" aria-hidden="true"></span> Cancel').removeClass("btn-success").addClass("btn-danger");
            $("#control-check-expected-value-battery").hide();
            if (value == 1) {
                $("#control-battery-volume").html("Ordered: <b>1MW</b>");
                $("#total_load").html("5.4");
                $("#total_value").html("240,000");
            }
            else {
                $("#control-battery-volume").html("Ordered: <b>2MW</b>");
                $("#total_load").html("6.4");
                $("#total_value").html("250,000");
            }
            batteryOrdered = true;
        }
    });

    // activate tooltips
    $('[data-toggle="tooltip"]').tooltip();
}

const numberWithCommas = (x) => {
    var parts = x.toString().split(".");
    parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
    return parts.join(".");
}

/** Analytics: Submit the resource selector, but reload to a clean URL,
               without any existing resource selection (confusing)
*/
var empty_location = location.protocol + "//" + location.hostname + ":" + location.port + "/analytics";

function submit_resource() {
    $("#resource-form").attr("action", empty_location).submit();
}
function submit_market() {
    $("#market-form").attr("action", empty_location).submit();
}
function submit_sensor_type() {
    $("#sensor_type-form").attr("action", empty_location).submit();
}
