# proxyrules

This example shows how to use the `proxyrules` strategy. This strategy lets you define rules in a YAML-based microformat that control how to proxy requests coming into mockstack to the other services.

* The included `.env.example` file should be renamed `.env` and contains the needed configuration to use this strategy and point to the rules file.
* The rules file `rules.yml` showcases some of the capabilities supported for rule-based proxying.


Some of the notable features for this strategy are:

* Can configure whether proxuying is done via Http redirects (Temporary Redirect, Permanent Redirect) or reverse proxying (e.g. silently re-routing request). Default is to reverse proxy.
* Can configure rules per URL mask and optionally limit a rule to specific HTTP methods.
* Can use regular expression capture groups to refer to matched groups in the "pattern" field when constructring the destination URL.
* All request metadata and content, including headers, query parameters, and request body when applicable (e.g. for POSTs) will be proxied through.
* Can simulate creation of resources for cases where we do not wish to proxy the request to a "real" service where creation might have undesirable sideeffects, and instead wish to simply simulate a realistic flow of creating a new resource. This is powered by the same mixin functionality thats used by the other strategies for simulation creation.
