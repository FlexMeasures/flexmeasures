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
    
    $('input[name="daterange"]').daterangepicker({
        "timePicker": true,
        "timePickerIncrement": 15,
        locale: {
            format: 'YYYY-MM-DD h:mm A'
        },
        "ranges": {
            'Today': [moment().startOf('day'), moment().endOf('day')],
            'Yesterday': [moment().subtract(1, 'days').startOf('day'), moment().subtract(1, 'days').endOf('day')],
            'This week': [moment().startOf('week').startOf('week'), moment().endOf('week').endOf('week')],
            'Last 7 Days': [moment().subtract(6, 'days').startOf('day'), moment().endOf('day')],
            'Last 30 Days': [moment().subtract(29, 'days').startOf('day'), moment().endOf('day')],
            'This Month': [moment().startOf('month').startOf('month'), moment().endOf('month').endOf('month')],
            'Last Month': [moment().subtract(1, 'month').startOf('month'), moment().subtract(1, 'month').endOf('month')]
        },
        "linkedCalendars": false,
        "startDate": timerangeStart,
        "endDate": timerangeEnd
    }, function(start, end, label) {
      console.log('New date range selected: ' + start.format('YYYY-MM-DD HH:mm') + ' to ' + end.format('YYYY-MM-DD HH:mm') + ' (predefined range: ' + label + ')');
      //$("#datepicker_form").action = "/" + location.pathname;
      $("#datepicker_form_start_time").val(start.format('YYYY-MM-DD HH:mm') );
      $("#datepicker_form_end_time").val(end.format('YYYY-MM-DD HH:mm') );
      $("#datepicker_form").submit(); // reload page with new time range
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