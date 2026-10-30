"""End-to-end tests: the real web page talking to the real backend in a browser."""
from playwright.sync_api import Page, expect


def select_germany(page: Page) -> None:
    """Click Germany on the map (the only selectable country)."""
    page.locator("#map path.leaflet-interactive").first.click()
    expect(page.get_by_test_id("country-info")).to_contain_text("Deutschland")


def test_solve_is_disabled_until_germany_is_selected(app_page: Page):
    expect(app_page.get_by_test_id("solve-button")).to_be_disabled()

    select_germany(app_page)

    expect(app_page.get_by_test_id("solve-button")).to_be_enabled()


def test_only_germany_is_clickable_on_the_map(app_page: Page):
    assert app_page.locator("#map path.leaflet-interactive").count() == 1


def test_priority_list_small_day_shows_results_and_chart(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("method").select_option("priority_list")
    app_page.get_by_test_id("scenario").select_option("small")
    app_page.get_by_test_id("horizon").select_option("day")

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("r-feasible")).to_have_text("ja", timeout=60000)
    expect(app_page.get_by_test_id("r-cost")).to_contain_text("€")
    expect(app_page.get_by_test_id("r-vars")).to_contain_text("binär")
    expect(app_page.get_by_test_id("day-section")).to_have_count(1)
    expect(app_page.get_by_test_id("day-cost")).to_contain_text("€")
    expect(app_page.locator("#days canvas")).to_be_visible()


def test_week_horizon_shows_seven_days_below_each_other_with_costs(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("horizon").select_option("week")

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("r-feasible")).to_be_visible(timeout=60000)
    expect(app_page.get_by_test_id("day-section")).to_have_count(7)
    expect(app_page.get_by_test_id("day-cost")).to_have_count(7)
    assert app_page.locator("#day").count() == 0   # no day dropdown any more


def test_exact_method_shows_gap_and_solver_time(app_page: Page):
    select_germany(app_page)
    expect(app_page.get_by_test_id("time-limit")).to_be_hidden()   # not used by the heuristic
    app_page.get_by_test_id("method").select_option("exact")
    expect(app_page.get_by_test_id("time-limit")).to_be_visible()
    app_page.get_by_test_id("time-limit").fill("60")
    app_page.get_by_test_id("mip-gap").fill("5")

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("r-feasible")).to_have_text("ja", timeout=120000)
    expect(app_page.get_by_test_id("r-solver-time")).to_contain_text("s")
    expect(app_page.get_by_test_id("r-gap")).not_to_have_text("")


def test_unimplemented_methods_are_greyed_out_and_cannot_be_chosen(app_page: Page):
    select_germany(app_page)

    expect(app_page.locator("#method option[value=ea]")).to_be_disabled()
    expect(app_page.locator("#method option[value=exact]")).to_be_enabled()
    expect(app_page.locator("#method option[value=priority_list]")).to_be_enabled()
    assert app_page.get_by_test_id("method").input_value() == "priority_list"


def test_info_texts_change_with_the_selection(app_page: Page):
    method_info = app_page.get_by_test_id("method-info")
    scenario_info = app_page.get_by_test_id("scenario-info")
    month_info = app_page.get_by_test_id("month-info")

    app_page.get_by_test_id("method").select_option("exact")
    exact_text = method_info.inner_text()
    app_page.get_by_test_id("method").select_option("priority_list")
    assert method_info.inner_text() != exact_text

    app_page.get_by_test_id("scenario").select_option("small")
    small_text = scenario_info.inner_text()
    app_page.get_by_test_id("scenario").select_option("large")
    assert scenario_info.inner_text() != small_text

    app_page.get_by_test_id("month").select_option("3")
    expect(month_info).to_contain_text("März")


def test_language_can_be_switched_and_is_remembered(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("month").select_option("3")

    app_page.get_by_test_id("language").click()
    app_page.locator('[data-language="en"]').click()

    expect(app_page.get_by_test_id("solve-button")).to_have_text("Start optimization")
    expect(app_page.get_by_test_id("language").locator("img")).to_have_attribute("alt", "Flag of the United Kingdom")
    expect(app_page.get_by_test_id("country-info")).to_contain_text("Germany")
    expect(app_page.get_by_test_id("month-info")).to_contain_text("March")
    assert app_page.get_by_test_id("month").input_value() == "3"   # selection survives the switch

    app_page.reload()
    app_page.wait_for_function("document.querySelectorAll('#method option').length > 0", timeout=60000)
    expect(app_page.get_by_test_id("solve-button")).to_have_text("Start optimization")


def test_results_follow_the_language(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("solve-button").click()
    expect(app_page.get_by_test_id("r-feasible")).to_have_text("ja", timeout=60000)
    expect(app_page.get_by_test_id("computing")).to_be_hidden()

    app_page.get_by_test_id("language").click()
    app_page.locator('[data-language="en"]').click()

    expect(app_page.get_by_test_id("r-feasible")).to_have_text("yes")
    expect(app_page.get_by_test_id("day-cost")).to_contain_text("Cost")


def test_exact_run_stopped_at_the_time_limit_is_explained(app_page: Page):
    select_germany(app_page)
    app_page.get_by_test_id("method").select_option("exact")
    app_page.get_by_test_id("scenario").select_option("medium")
    app_page.get_by_test_id("horizon").select_option("week")
    app_page.get_by_test_id("time-limit").fill("1")

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("limit-note")).to_be_visible(timeout=120000)
    expect(app_page.get_by_test_id("r-build-time")).to_contain_text("s")


def test_lost_job_shows_clear_message(app_page: Page):
    # Simulate a server restart: it no longer knows the job
    app_page.route(
        "**/jobs/*",
        lambda route: route.fulfill(status=404, content_type="application/json", body='{"detail": "Unknown job"}'),
    )
    select_germany(app_page)

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("status")).to_contain_text("Auftrag ging verloren", timeout=30000)
    expect(app_page.get_by_test_id("solve-button")).to_be_enabled()


def test_short_connection_problems_while_polling_are_retried(app_page: Page):
    failed_requests = []

    def flaky_jobs(route):
        """Fail the first two status requests like a restarting server, then let them through."""
        if len(failed_requests) < 2:
            failed_requests.append(route.request.url)
            route.abort()
        else:
            route.continue_()

    app_page.route("**/jobs/*", flaky_jobs)
    select_germany(app_page)

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("r-feasible")).to_have_text("ja", timeout=60000)
    assert len(failed_requests) == 2


def test_unreachable_server_shows_helpful_message(app_page: Page):
    select_germany(app_page)
    # The server disappears after the page has loaded and never comes back
    app_page.route("**/health", lambda route: route.abort())
    app_page.route("**/solve", lambda route: route.abort())

    app_page.get_by_test_id("solve-button").click()

    expect(app_page.get_by_test_id("status")).to_contain_text("Server wird aufgeweckt")
