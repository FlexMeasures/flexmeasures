{#- Override sort order to prefer looking at the most recent past first, workaround for https://github.com/Parallels/rq-dashboard/issues/123 -#}
function updateLinks() {
    document.querySelectorAll('td.failed a, td.narrow a').forEach(link => {
        const href = link.getAttribute('href');
        if (href.includes('/canceled/') || href.includes('/failed/') || href.includes('/finished/')) {
            const newHref = href.replace('/asc/', '/dsc/');
            link.setAttribute('href', newHref);
        }
    });
}

// Function to check if the table is done loading
function checkTableAndUpdate(mutationsList, observer) {
    const loadingRow = document.querySelector('tbody tr');
    if (loadingRow && loadingRow.textContent.trim() !== 'Loading...') {
        updateLinks();
        observer.disconnect();  // Stop observing once the table is updated
    }
}

// Monitor the tbody for changes
const observer = new MutationObserver(checkTableAndUpdate);

// Start observing the tbody element for child list changes
const tbody = document.querySelector('tbody');
observer.observe(tbody, { childList: true, subtree: true });
