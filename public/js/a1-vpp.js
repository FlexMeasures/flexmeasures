$(document).ready(function() {			
    ready();
});

function ready() {

    $('#settings-processes').ionRangeSlider({
        grid: true,
        grid_snap: true,
        values: ["1MW", "2MW", "3MW"],
        force_edges: true,
        onFinish: function (data) {
            getData();
        }
    });

    $('#settings-processes-2').ionRangeSlider({
        grid: true,
        grid_snap: true,
        values: ["1MW", "2MW", "3MW"],
        force_edges: true,
        onFinish: function (data) {
            getData();
        }
    });

    $('#settings-processes-3').ionRangeSlider({
        grid: true,
        grid_snap: true,
        values: ["1MW", "2MW", "3MW"],
        force_edges: true,
        onFinish: function (data) {
            getData();
        }
    });
    
    $('#settings-processes-4').ionRangeSlider({
        grid: true,
        grid_snap: true,
        values: ["1MW", "2MW", "3MW"],
        force_edges: true,
        onFinish: function (data) {
            getData();
        }
    });

    $('#settings-processes-5').ionRangeSlider({
        grid: true,
        grid_snap: true,
        values: ["1MW", "2MW", "3MW"],
        force_edges: true,
        onFinish: function (data) {
            getData();
        }
    });
    
    $('#settings-processes-6').ionRangeSlider({
        grid: true,
        grid_snap: true,
        values: ["1MW", "2MW", "3MW"],
        force_edges: true,
        onFinish: function (data) {
            getData();
        }
    });
    
    $('#settings-preset-dist').bind('change', function() {
        if ($('#settings-preset-dist').val() == 'h') {
            $("img[name=preset-icon]").attr("src", "public/icons/sun.svg");
        } else if ($('#settings-preset-dist').val() == 'b') {
            $("img[name=preset-icon]").attr("src", "public/icons/test.svg");
        } else if ($('#settings-preset-dist').val() == 'ev-o') {
            $("img[name=preset-icon]").attr("src", "public/icons/sun.svg");
        } else if ($('#settings-preset-dist').val() == 'ev-p') {
            $("img[name=preset-icon]").attr("src", "public/icons/wind.svg");
        } else if ($('#settings-preset-dist').val() == 'ev-s') {
            $("img[name=preset-icon]").attr("src", "public/icons/battery.svg");
        } else {
            $("img[name=preset-icon]").attr("src", "public/icons/car.svg");
        }
    });
    
}