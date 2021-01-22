$(document).ready(function() {

    $('input[name="daterange"]').daterangepicker({
        "timePicker": true,
        "timePickerIncrement": 15,
        locale: {
            format: 'YYYY-MM-DD h:mm A'
        },
        "ranges": {
            'Tomorrow': [moment().add(1, 'day').startOf('day'), moment().add(1, 'day').endOf('day')],
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
      $("#datepicker_form_start_time").val(start.format('YYYY-MM-DD HH:mm') );
      $("#datepicker_form_end_time").val(end.format('YYYY-MM-DD HH:mm') );
      // remove any URL params from an earlier call and point to whatever resource is actually selected
      $("#datepicker_form").attr("action", location.pathname + "?resource=" + $("#resource").val());
      $("#datepicker_form").submit(); // reload page with new time range
    });
});
