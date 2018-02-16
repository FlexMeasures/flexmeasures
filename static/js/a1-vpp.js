$(document).ready(function() {			
    ready();
});

var offshoreOrdered = false;


function showMsg(msg){
    $("#msgModal .modal-content").html(msg);
    $("#msgModal").modal("show");
}

function showImage(resource, action, value){
//    $("#expectedValueModal .modal-dialog .modal-content img").html("static/control-mock-imgs/" + resource + "-action" + action + "-" + value + "MW.png")
    document.getElementById('expected_value_mock').src = "static/control-mock-imgs/value-" + resource + "-action" + action + "-" + value + "MW.png"
    load_images = document.getElementsByClassName('expected_load_mock')
    for (var i = 0; i < load_images.length; i++) {
        load_images[i].src = "static/control-mock-imgs/load-" + resource + "-action" + action + "-" + value + "MW.png"
    }
}


function defaultImage(action){
    load_images = document.getElementsByClassName('expected_load_mock reset_default')
    for (var i = 0; i < load_images.length; i++) {
        load_images[i].src = "static/control-mock-imgs/load-action" + action + ".png"
    }
}


function ready() {

    console.log("ready...");


    // Sliders

    $('#control-action-setting-offshore')
    .ionRangeSlider({
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
        onChange: function(settingData){
            action = 1;
            if (offshoreOrdered){
                action = 2;
            }
            value = settingData.from;
            $("#control-expected-value-offshore").html(numberWithCommas(value * 35000));
            showImage("offshore", action, value);
        }
     });

    $('#control-action-setting-battery').ionRangeSlider({
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
        onChange: function(settingData){
            action = 1;
            if (offshoreOrdered){
                action = 2;
            }
            value = settingData.from;
            $("#control-expected-value-battery").html(numberWithCommas(value * 10000));
            showImage("battery", action, value);
        }
    });



    // Hover behaviour

    $("#control-tr-offshore").mouseenter(function(data){
        action = 1;
        if (offshoreOrdered){
            action = 2;
        }
        var value = $("#control-action-setting-offshore").data("ionRangeSlider").old_from;
        showImage("offshore", action, value);
    }).mouseleave(function(data){
        action = 1;
        if (offshoreOrdered){
            action = 2;
        }
        defaultImage(action);
    });

    $("#control-tr-battery").mouseenter(function(data){
        action = 1;
        if (offshoreOrdered){
            action = 2;
        }
        var value = $("#control-action-setting-battery").data("ionRangeSlider").old_from;
        showImage("battery", action, value);
    }).mouseleave(function(data){
        action = 1;
        if (offshoreOrdered){
            action = 2;
        }
        defaultImage(action);
    });


    // Table behaviour

    $('table').floatThead({
        position: 'absolute',
        scrollContainer: true
    });


    // Check button behaviour

    $("#control-check-expected-value-offshore").click(function(data){
        var value = $("#control-action-setting-offshore").data("ionRangeSlider").old_from;
        showImage("offshore", 1, value);
        $("#expectedValueModal").modal("show");
    });

    $("#control-check-expected-value-battery").click(function(data){
        var value = $("#control-action-setting-battery").data("ionRangeSlider").old_from;
        action = 1;
        if (offshoreOrdered){
            action = 2;
        }
        showImage("battery", action, value);
        $("#expectedValueModal").modal("show");
    });


    // Order button behaviour

    $("#control-order-button-ev").click(function(data){
        showMsg("This action is not supported in this mockup.");
    });

    $("#control-order-button-onshore").click(function(data){
        showMsg("This action is not supported in this mockup.");
    });

    $("#control-order-button-offshore").click(function(data){
        if (offshoreOrdered){
            showMsg("This action is not supported in this mockup.");
        }
        var value = $("#control-action-setting-offshore").data("ionRangeSlider").old_from;
        console.log("Offshore was ordered for " + value + "MW!");
        if (value == 2){
            showMsg("Your order of " + value + "MW offshore wind curtailment will be processed!");
            $("#control-tr-offshore").addClass("active");
            $("#control-offshore-volume").html("Ordered: <b>2MW</b>");
            $("#control-order-button-offshore").html('<span class="fa fa-minus" aria-hidden="true"></span> Cancel');
            $("#control-check-expected-value-offshore").hide();
            $("#total_load").html("4.4");
            $("#total_value").html("230,000");
            offshoreOrdered = true;
        }
        else{
            showMsg("In this mockup, only ordering 2MW of offshore wind is supported.");
        }
    });

    $("#control-order-button-battery").click(function(data){
        if (!offshoreOrdered){
            showMsg("In this mockup, please first order 2MW of offshore wind.");
        } else {
            var value = $("#control-action-setting-battery").data("ionRangeSlider").old_from;
            console.log("Battery was ordered for " + value + "MW!");
            showMsg("Your order of " + value + "MW battery shifting will be processed!");
            $("#control-check-expected-value-battery").hide();
        }
    });
}

const numberWithCommas = (x) => {
  var parts = x.toString().split(".");
  parts[0] = parts[0].replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return parts.join(".");
}