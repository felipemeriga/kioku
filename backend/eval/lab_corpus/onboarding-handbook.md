# Engineering Onboarding Handbook

Welcome to the team. This handbook walks through everything you need in your
first two weeks. Read it end to end; the details that matter are scattered
throughout, not gathered in one place.

## Week one: accounts and access

Your first day is mostly accounts. IT provisions your laptop the evening
before you start, so it should be waiting at your desk. Log in with the
temporary password from your welcome email and change it immediately. Set up
two-factor authentication on the internal identity provider before touching
anything else — most services refuse logins without it.

Once you can log in, request access to the code repositories through the
self-service portal. Access requests are reviewed twice a day, so you may
wait a few hours. While you wait, install the toolchain: the language
runtimes, the container tooling, and the editor plugins the team standardizes
on. The setup script in the platform repo handles most of this.

## Week one: your environment

Clone the main repositories and run the bootstrap script in each. The script
seeds a local database, downloads fixtures, and runs a smoke test. If the
smoke test fails, check that your container runtime has at least 8 GB of
memory allocated — the default is often too low and the failure is silent.

The team runs a daily standup at 10:00. It is optional in your first week but
attending helps you absorb context. Standups are short: what you did, what
you are doing, what is blocking you.

## Week two: your first change

By week two you should ship something small. Pick a starter issue tagged
"good first issue" from the tracker. The important operational detail for
your first deploy: the production deploy freeze runs every Friday from noon,
so nothing ships to production on Friday afternoons or over the weekend.
Plan your first merge for earlier in the week so it is not caught by the
freeze.

Code review requires two approvals before merge. Request review early — the
team reviews in the morning, so a pull request opened late in the day usually
lands the next morning. Keep changes small; large pull requests wait longer
and collect more comments.

## Culture

We value written communication. Decisions get recorded in the decision log so
that someone reading six months later understands not just what we chose but
why. If you find yourself explaining the same thing twice, write it down and
link it instead.

Ask questions early. Nobody expects you to know the system in your first
month, and a question that saves you a day of confusion is always worth it.
