/**
* Support for showing Toast messages in the lower right corner.
* 
* - Writes the necessary HTML
* - Handles logic to show / hide
* - Offers the main function for code to use: showToast(msg, type)
*
* All your document needs is to provide a div with id "toast-container" with a button in it with id "close-all-toasts". See base.html for the implementation of that.
*/

const toastStack = document.getElementById("toast-container");
const closeToastBtn = document.getElementById("close-all-toasts");

// written like this since this script(order) is ontop of the main script
document.addEventListener("DOMContentLoaded", function () {
  initiateToastCloseBtn(closeToastBtn);
});

function maybeHideCloseToastBtn() {
  const remainingToasts = toastStack.querySelectorAll(".toast");
  if (remainingToasts.length === 0) {
    closeToastBtn.style.display = "none";
  }
}

function initiateToastCloseBtn(closeToastBtn) {
  // hide button
  closeToastBtn.style.display = "none";

  closeToastBtn.addEventListener("click", function () {
    const toastElements = document.querySelectorAll(".toast");
    toastElements.forEach((toast) => {
      const toastInstance = bootstrap.Toast.getInstance(toast); // Get the toast instance
      if (toastInstance) {
        // destroy the toast
        toastInstance.dispose();
        toast.remove();
      }
    });
    // Hide the close button
    closeToastBtn.style.display = "none";
  });
}

function showAllToasts() {
  const toastElements = document.querySelectorAll(".toast");
  toastElements.forEach((toast) => {
    const toastInstance = new bootstrap.Toast(toast);
    toastInstance.show();
  });
}

function showToast(
  message,
  type,
  { highlightDuplicates = true, showDuplicateCount = true } = {}
) {
  let colorClass;
  let colorStyle = "";
  let title;

  // Determine the type of toast
  if (type == "error") {
    delay = 10000;
    colorClass = "bg-danger";
    title = "Error";
  } else if (type == "success") {
    delay = 2000;
    colorClass = "bg-success";
    title = "Success";
  } else {
    delay = 5000;
    colorStyle = "background-color: {{ primary_color }};";
    title = "Info";
  }

  // Search for an existing toast with the same message
  const existingToasts = toastStack.querySelectorAll(".toast");
  for (const t of existingToasts) {
    const body = t.querySelector(".toast-body");
    if (body && body.dataset.originalMessage === message) {
      // It's a duplicate
      if (showDuplicateCount) {
        let count = parseInt(body.dataset.count || "1") + 1;
        body.dataset.count = count;
        body.innerHTML = `${message} <span class="text-muted ms-2">(x${count})</span>`;
      }

      if (highlightDuplicates) {
        t.classList.remove("highlight");
        void t.offsetWidth; // Trigger reflow for CSS animation restart
        t.classList.add("highlight");
      }

      // Reinitialize and show the toast again
      const oldInstance = bootstrap.Toast.getInstance(t);
      if (oldInstance) {
        oldInstance.dispose();
      }
      const newInstance = new bootstrap.Toast(t);
      newInstance.show();

      return; // Don't create a new toast
    }
  }

  // Create the toast HTML
  const toast = document.createElement("div");
  toast.classList.add("toast", "mb-1");
  toast.setAttribute("data-bs-autohide", "true");
  toast.setAttribute("data-bs-delay", delay);
  toast.setAttribute("role", "alert");
  toast.setAttribute("aria-live", "assertive");
  toast.setAttribute("aria-atomic", "true");

  toast.innerHTML = `
              <div class="toast-header">
                <div class="rounded me-2 ${colorClass}" style="width: 20px; height: 20px; display: inline-block; ${colorStyle}"></div>
                <strong class="me-auto">${title}</strong>
                <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
              </div>
            <div class="toast-body" data-original-message="${message}" data-count="1">
                ${message}
              </div>
            `;

  // Append toast to the toast stack
  toastStack.insertAdjacentElement("afterbegin", toast);

  // Show the close all button
  closeToastBtn.style.display = "block";

  showAllToasts();

  // Dispose and remove toast when it's autohidden
  toast.addEventListener("hidden.bs.toast", function () {
    const instance = bootstrap.Toast.getInstance(toast);
    if (instance) {
      instance.dispose();
    }
    toast.remove();
    maybeHideCloseToastBtn();
  });

  // destroy only this toast if the close(X) button is clicked
  toast.querySelector(".btn-close").addEventListener("click", function () {
    const toastInstance = new bootstrap.Toast(toast);
    toastInstance.dispose();
    toast.remove();
    maybeHideCloseToastBtn();
  });
}
