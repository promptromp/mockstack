# filefixtures example

This folder shows an example setup for using mockstack with the `filefixtures` strategy which lets you route
requests to template files.

The folder is comprised of the following:

An `.env.example` file which you would rename `.env` and contains the relevant configuration options needed to run. When you have that file in the working directory when invoking mockstack it will automatically pick up the settings from this file.

A `templates/` dir, pointed to by a configurationkey in the env file, which contains our templates.
We have a few example templates showcasing some of the capabilities of template-based mocking:

* One template file shows how you can have Jinja2 templating conditionals in the template e.g. to handle different responses based on request query parameters.
* Another template shows the naming convention for templates that depend on an identifier embedded in the request URL, e.g. `GET
    /someservice/api/v1/item/ae420979-33f3-4c99-bc42-9d7cdee5259e` would get routed to the template file `someservice-api-v1-item.ae420979-33f3-4c99-bc42-9d7cdee5259e.j2`.
* Multiple identifiers in the path are also supported and would appear in filenames separated by dots, according to the order in which they appear in the URL.
* A configuration value in controllable via `.env` / environment variables lets you also decide whether to allow using templates for POST requests or try to simulate a createion. When templates are allowed, mockstaack will first try to find a suitable template for the request based on the URL, and if it fails will fallback to the create simulation behavior.
