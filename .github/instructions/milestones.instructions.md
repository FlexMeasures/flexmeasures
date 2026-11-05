---
applyTo: "**"
---
# Milestones

Each pull request gets a milestone: the first release that will ship it.
The `milestone` check (`.github/workflows/milestone-check.yml`) enforces this,
so a pull request cannot pass while its milestone is missing, closed, or at odds with its changelog entry.

## When opening a pull request

- Set the milestone to the open milestone of the release that will ship the change.
  List the open milestones with `gh api repos/FlexMeasures/flexmeasures/milestones --jq '.[].title'`.
  Usually that is the next minor release from `main`.
  A fix that will be backported to a release branch gets the milestone of that patch release instead.
- Make the main changelog (`documentation/changelog.rst`) agree with it:
  an entry linking the pull request must sit under the release heading (`vX.Y.Z | ...`) that matches the milestone `X.Y.Z`.
  If that release has no section yet, add one, keeping the sections in version order.
  The API changelog follows the API's own versions, and the CLI changelog does not link pull requests, so the check reads neither.
- If the milestone you need does not exist yet, create it with the bare version number as its title, like `1.2.0`, not `v1.2.0`.
- Contributors without write access cannot set a milestone; a maintainer sets it, and the check re-runs on its own.

## Before merging

Check the milestone again: a release may have gone out since the pull request was opened.
The check re-runs when a milestone is closed, so a stale milestone shows as a failing check.
Move the pull request to the release that will now ship it, and move its changelog entry to that release's section.

## When backporting

A backported pull request ships first in the patch release, so move the original pull request to that patch milestone,
give the backport pull request (if there is one) the same milestone,
and move the changelog entry on `main` into that patch release's section.
Backport commits are titled `Backport PR #NNNN: <original title>`.
