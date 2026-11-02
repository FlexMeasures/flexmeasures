/** Explain how a selected plan affects the organisation's current usage. */
export function planQuotaWarnings(usage, limits) {
  const warnings = [];
  const resources = [
    ["users", "active users", "users can be activated or added"],
    ["assets", "assets (including sub-assets)", "assets can be added or transferred in"],
    ["clients", "client organisations", "clients can be added"],
  ];
  for (const [key, label, action] of resources) {
    const limit = limits[key];
    if (limit === null || usage[key] < limit || (key === "clients" && limit === 0 && usage[key] === 0)) continue;
    warnings.push(
      `This organisation has ${usage[key]} ${label}; the selected plan allows ${limit}. ` +
      `Existing ${label} will remain. ` +
      (limit === 0
        ? `No ${action} on this plan.`
        : `No more ${action} until usage is below ${limit}.`)
    );
  }
  if (limits.clients === 0) {
    warnings.push("Existing consultancy roles remain, but new consultant roles cannot be granted and clients cannot be added on this plan.");
  }
  return warnings;
}

/** Update the warning when an administrator selects a plan. */
export function initPlanQuotaWarning(select, warning) {
  if (!select || !warning) return;
  const usage = {
    users: Number(select.dataset.users),
    assets: Number(select.dataset.assets),
    clients: Number(select.dataset.clients),
  };
  function update() {
    const option = select.selectedOptions[0];
    const readLimit = (key) => option.dataset[key] === undefined || option.dataset[key] === ""
      ? null : Number(option.dataset[key]);
    const warnings = planQuotaWarnings(usage, {
      users: readLimit("maxUsers"),
      assets: readLimit("maxAssets"),
      clients: readLimit("maxClients"),
    });
    warning.textContent = warnings.join("\n");
    warning.hidden = warnings.length === 0;
  }
  select.addEventListener("change", update);
  update();
}
