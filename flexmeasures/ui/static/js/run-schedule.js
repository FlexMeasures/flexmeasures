/** A deliberately small, on-demand wizard for a single device. */
export function initializeRunSchedule(root, config) {
    const el = name => root.querySelector(`[data-role="${name}"]`);
    let options = null;
    let checkedPeriod = null;
    let loading = false;
    let running = false;
    let generation = 0;
    let controller;
    let savedChoices = null;
    const show = (name, visible) => el(name).classList.toggle('d-none', !visible);
    const notify = (message, type = 'info') => {
        el('status').textContent = message;
        el('status').classList.remove('d-none', 'alert-info', 'alert-success', 'alert-danger');
        el('status').classList.add(type === 'error' ? 'alert-danger' : `alert-${type}`);
        window.showToast(message, type);
    };
    const missing = value => value === null || value === undefined;
    const errorMessage = data => {
        const message = data.message || data.error || data;
        return typeof message === 'string' ? message : JSON.stringify(message);
    };
    async function jsonResponse(response) {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(errorMessage(data) || response.statusText);
        return data;
    }
    function period() {
        const start = new Date(el('start').value);
        const hours = Number(el('duration').value);
        if (!el('start').value || !Number.isFinite(start.getTime()) || !Number.isFinite(hours) || hours <= 0) {
            throw new Error('Choose a valid start time and a positive duration.');
        }
        const end = new Date(start.getTime() + hours * 3600000);
        return {start: start.toISOString(), end: end.toISOString(), duration: `PT${Math.round(hours * 3600)}S`};
    }
    function hasStartingSoc() {
        return Boolean(el('soc-source').value) ||
            (el('soc').value !== '' && el('soc').checkValidity());
    }
    function updateSocWarning() {
        const warning = el('soc-warning');
        if (warning) warning.classList.toggle('d-none', hasStartingSoc());
        const hasWarnings = [...el('warnings').children].some(note => !note.classList.contains('d-none'));
        show('warnings', hasWarnings);
        return hasWarnings;
    }
    function updateReady() {
        let validPeriod = true;
        try {
            const range = period();
            validPeriod = checkedPeriod && range.start === checkedPeriod.start && range.duration === checkedPeriod.duration;
        } catch { validPeriod = false; }
        const hasSoc = hasStartingSoc();
        const ready = options && options.power_sensors.length === 1 && validPeriod &&
            options.price_available !== false &&
            (!missing(options.consumption_price) || el('price').value) &&
            (!missing(options.power_capacity) || Number(el('capacity').value) > 0) &&
            (!options.requires_soc || hasSoc);
        el('run').disabled = loading || running || !ready;
        el('run-tooltip').title = el('run').disabled ? 'Disable, check prerequisites warnings.' : '';
        el('run-tooltip').tabIndex = el('run').disabled ? 0 : -1;
        el('price').disabled = loading || running;
        el('capacity').disabled = loading || running;
        el('soc-source').disabled = loading || running;
        el('soc').disabled = running || Boolean(el('soc-source').value);
        el('soc-unit').disabled = el('soc').disabled;
        show('spinner', loading || running);
        updateSocWarning();
    }
    function addOption(select, value, text) {
        const option = document.createElement('option');
        option.value = value;
        option.textContent = text;
        select.append(option);
    }
    function showSensorLink(output, sensor) {
        const link = document.createElement('a');
        link.href = sensor.url;
        link.textContent = sensor.name;
        output.replaceChildren(link, ` (${sensor.unit}, ID: ${sensor.id})`);
    }
    function updateSelectedPrice() {
        const sensor = options?.price_sensors.find(item => String(item.id) === el('price').value);
        if (sensor) showSensorLink(el('selected-price'), sensor);
        else el('selected-price').replaceChildren();
    }
    async function lookup() {
        if (running) return;
        const currentGeneration = ++generation;
        if (controller) controller.abort();
        controller = new AbortController();
        options = null;
        loading = true;
        show('retry', false);
        updateReady();
        try {
            const range = period();
            notify('Checking prerequisites and looking for price and state-of-charge data…');
            const url = new URL(config.optionsUrl, window.location.origin);
            url.searchParams.set('start_time', range.start);
            url.searchParams.set('end_time', range.end);
            const data = await jsonResponse(await fetch(url, {signal: controller.signal}));
            if (currentGeneration !== generation) return;
            options = data;
            checkedPeriod = range;
            const warnings = [...(data.warnings || [])];
            const powers = data.power_sensors;
            el('power').replaceChildren();
            if (powers.length === 1) showSensorLink(el('power'), powers[0]);
            if (!powers.length) {
                el('power').textContent = 'None; see info below.';
                warnings.push('This asset has no power sensor, so it is not supported by this Run schedule dialogue. Add a power sensor to this asset to use it.');
            } else if (powers.length > 1) {
                el('power').append('More than one (IDs: ');
                for (const [index, sensor] of powers.entries()) {
                    if (index) el('power').append(', ');
                    const link = document.createElement('a');
                    link.href = sensor.url;
                    link.textContent = String(sensor.id);
                    el('power').append(link);
                }
                el('power').append('); see info below.');
                warnings.push('This asset has multiple power sensors, so it is not supported by this Run schedule dialogue yet. Support for scheduling multiple power sensors here is coming soon. For now, configure multi-device scheduling in flex-config and use the scheduling API.');
            }
            const previousPrice = el('price').value;
            el('price').replaceChildren();
            addOption(el('price'), '', 'Choose a price sensor');
            for (const sensor of data.price_sensors) addOption(el('price'), sensor.id, `${sensor.name} (${sensor.unit}, ID: ${sensor.id})`);
            el('price').value = previousPrice;
            show('price-group', missing(data.consumption_price));
            show('configured-price-group', !missing(data.consumption_price));
            el('configured-price').replaceChildren();
            if (data.consumption_price_sensor) showSensorLink(el('configured-price'), data.consumption_price_sensor);
            else if (!missing(data.consumption_price)) el('configured-price').textContent =
                typeof data.consumption_price === 'string' || typeof data.consumption_price === 'number'
                    ? String(data.consumption_price) : 'Configured price sensor unavailable';
            updateSelectedPrice();
            if (missing(data.consumption_price)) {
                warnings.push(data.price_sensors.length ? 'No consumption price is configured. Choose a price sensor for this run.' : 'No price sensors with prices known now and covering the full schedule were found. A chart may show future values whose belief times are later than now. Check the price sensor data and its belief horizon, or create a price sensor and upload a CSV, then check prerequisites again.');
            }
            if (data.price_available === false) warnings.push('The configured consumption price sensor has no prices known now covering the full schedule. A chart may show future values whose belief times are later than now. Check its belief horizon or add price data, or update the asset’s flex-config to use a different sensor.');
            show('capacity-group', missing(data.power_capacity));
            if (missing(data.power_capacity)) warnings.push('No power capacity is configured. Enter the device’s power limit for this run.');
            el('capacity').required = missing(data.power_capacity);
            const previousSocSource = el('soc-source').value;
            el('soc-source').replaceChildren();
            show('soc-source', data.soc_sensors.length > 0);
            addOption(el('soc-source'), '', 'Choose an existing SoC reading');
            for (const sensor of data.soc_sensors) {
                addOption(el('soc-source'), sensor.id, `${sensor.name}: ${sensor.value} ${sensor.unit} at ${sensor.event_start}`);
            }
            el('soc-source').value = previousSocSource;
            el('warnings').replaceChildren();
            for (const warning of warnings) {
                const p = document.createElement('p');
                p.className = 'mb-1';
                p.textContent = warning;
                el('warnings').append(p);
            }
            if (data.requires_soc) {
                const p = document.createElement('p');
                p.dataset.role = 'soc-warning';
                p.className = 'mb-1';
                p.textContent = 'A starting state of charge is required for this storage asset. Choose an existing SoC reading or enter a value before running.';
                el('warnings').append(p);
            }
            const hasWarnings = updateSocWarning();
            show('retry', true);
            notify(hasWarnings ? 'Prerequisites checked. Review the notes before running.' : 'Prerequisites checked.', 'info');
        } catch (error) {
            if (currentGeneration !== generation || error.name === 'AbortError') return;
            notify(`Could not check prerequisites: ${error.message}`, 'error');
            show('retry', true);
        } finally {
            if (currentGeneration === generation) {
                loading = false;
                updateReady();
            }
        }
    }
    root.addEventListener('show.bs.modal', () => {
        if (!el('start').value) {
            const date = new Date();
            date.setHours(date.getHours() + 1, 0, 0, 0);
            const local = new Date(date.getTime() - date.getTimezoneOffset() * 60000);
            el('start').value = local.toISOString().slice(0, 16);
        }
        el('timezone').textContent = `Times use your browser timezone: ${Intl.DateTimeFormat().resolvedOptions().timeZone}. Duration is elapsed hours, including across daylight-saving changes.`;
        lookup();
    });
    for (const name of ['start', 'duration']) {
        el(name).addEventListener('change', lookup);
        el(name).addEventListener('input', updateReady);
    }
    for (const name of ['price', 'capacity', 'soc-source']) el(name).addEventListener('change', () => {
        if (name === 'price') updateSelectedPrice();
        updateReady();
    });
    el('soc').addEventListener('input', updateReady);
    el('retry').addEventListener('click', event => {
        event.preventDefault();
        lookup();
    });
    el('form').addEventListener('submit', async event => {
        event.preventDefault();
        if (el('run').disabled || !el('form').reportValidity()) return;
        running = true;
        el('inputs').disabled = true;
        show('results', false);
        show('save-group', false);
        savedChoices = null;
        updateReady();
        try {
            const range = period();
            const sensor = options.power_sensors[0];
            const model = {sensor: sensor.id};
            const choices = {};
            const payload = {start: range.start, duration: range.duration, 'force-new-job-creation': el('force').checked};
            if (missing(options.consumption_price)) {
                choices.consumption_price_sensor = Number(el('price').value);
                payload['flex-context'] = {'consumption-price': {sensor: choices.consumption_price_sensor}};
            }
            if (missing(options.power_capacity)) {
                choices.power_capacity = `${Number(el('capacity').value)} kW`;
                model['power-capacity'] = choices.power_capacity;
            }
            const soc = options.soc_sensors.find(item => String(item.id) === el('soc-source').value);
            if (soc) model['soc-at-start'] = `${soc.value} ${soc.unit}`;
            else if (el('soc').value !== '') model['soc-at-start'] = `${Number(el('soc').value)} ${el('soc-unit').value}`;
            payload['flex-model'] = [model];
            notify('Queuing schedule…');
            const job = await jsonResponse(await fetch(config.triggerUrl, {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload)
            }));
            const jobId = job.job || job.schedule;
            if (!jobId) throw new Error('The scheduling response did not contain a job ID.');
            notify('Schedule queued. Waiting for execution…');
            for (let attempt = 0; attempt < 100; attempt++) {
                await new Promise(resolve => setTimeout(resolve, 3000));
                const response = await fetch(`${config.jobsUrl}/${encodeURIComponent(jobId)}`);
                const status = await jsonResponse(response);
                if (response.status === 200) {
                    notify('Schedule finished. The schedule data is ready.', 'success');
                    const link = document.createElement('a');
                    const url = new URL(sensor.url, window.location.origin);
                    const contextHours = 5 * 3600000;
                    url.searchParams.set('start_time', new Date(new Date(range.start).getTime() - contextHours).toISOString());
                    url.searchParams.set('end_time', new Date(new Date(range.end).getTime() + contextHours).toISOString());
                    link.href = url.toString();
                    link.className = 'btn btn-primary';
                    link.textContent = 'See it here';
                    el('results').replaceChildren(link);
                    show('results', true);
                    if (Object.keys(choices).length && options.can_save) {
                        savedChoices = choices;
                        el('save-summary').textContent = `Keep these temporary choices for future schedules? ${choices.consumption_price_sensor ? `Price sensor #${choices.consumption_price_sensor}. ` : ''}${choices.power_capacity ? `Power capacity: ${choices.power_capacity}.` : ''}`;
                        show('save-group', true);
                    }
                    return;
                }
                notify(status.message || `Schedule ${status.status.toLowerCase()}…`);
            }
            notify('Still waiting for the schedule after five minutes. The job may continue in the background; check the Jobs page before submitting again.', 'error');
        } catch (error) {
            notify(`Scheduling failed: ${error.message}`, 'error');
        } finally {
            running = false;
            el('inputs').disabled = false;
            updateReady();
        }
    });
    el('save').addEventListener('click', async () => {
        if (!savedChoices) return;
        el('save').disabled = true;
        try {
            await jsonResponse(await fetch(config.defaultsUrl, {
                method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(savedChoices)
            }));
            show('save-group', false);
            notify('Defaults saved to the asset’s flex-config.', 'success');
            savedChoices = null;
            await lookup();
        } catch (error) {
            notify(`Could not save defaults: ${error.message}`, 'error');
        } finally {
            el('save').disabled = false;
        }
    });
}
