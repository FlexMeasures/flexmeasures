"""Browser checks for the plan selector's quota warnings."""


def test_plan_selection_warns_about_usage_and_consultancy_roles(assert_js):
    assert_js("""
        import { initPlanQuotaWarning, planQuotaWarnings } from "/js/plan-quota-warning.js";
        const select = document.createElement("select");
        select.dataset.users = "5";
        select.dataset.assets = "12";
        select.dataset.clients = "3";
        select.innerHTML = `<option value="unlimited">Unlimited</option>
          <option value="limited" data-max-users="1" data-max-assets="5" data-max-clients="0">Limited</option>
          <option value="equal" data-max-users="5" data-max-assets="13" data-max-clients="4">At limit</option>`;
        const warning = document.createElement("div");
        initPlanQuotaWarning(select, warning);
        check("unlimited plan needs no warning", warning.hidden);
        select.value = "limited";
        select.dispatchEvent(new Event("change"));
        check("warning is visible", !warning.hidden);
        check("active user usage and limit", warning.textContent.includes("5 active users") && warning.textContent.includes("allows 1"), warning.textContent);
        check("sub-assets are counted", warning.textContent.includes("12 assets (including sub-assets)"), warning.textContent);
        check("client roles are explained", warning.textContent.includes("Existing consultancy roles remain") && warning.textContent.includes("new consultant roles cannot be granted"), warning.textContent);
        select.value = "equal";
        select.dispatchEvent(new Event("change"));
        check("a full quota warns that additions are blocked", warning.textContent.includes("5 active users") && warning.textContent.includes("below 5"), warning.textContent);
        select.value = "unlimited";
        select.dispatchEvent(new Event("change"));
        check("switching back clears the warning", warning.hidden && warning.textContent === "");
        const noClients = planQuotaWarnings({users: 0, assets: 0, clients: 0}, {users: null, assets: null, clients: 0}).join(" ");
        check("zero clients warns even when there are no existing clients", noClients.includes("new consultant roles cannot be granted") && noClients.includes("clients cannot be added"), noClients);
        """)
