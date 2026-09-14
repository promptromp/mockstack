# proxyrules

This example shows how to use the `proxyrules` strategy. This strategy lets you define rules in a YAML-based microformat that control how to proxy requests coming into mockstack to the other services.

* The included `.env.example` file should be renamed `.env` and contains the needed configuration to use this strategy and point to the rules file.
* The rules file `rules.yml` showcases some of the capabilities supported for rule-based proxying.


Some of the notable features for this strategy are:

* Can configure whether proxying is done via Http redirects (Temporary Redirect, Permanent Redirect) or reverse proxying (e.g. silently re-routing request). Default is to reverse proxy.
* Can configure rules per URL mask and optionally limit a rule to specific HTTP methods.
* Can use regular expression capture groups to refer to matched groups in the "pattern" field when constructing the destination URL.
* All request metadata and content, including headers (except hop-by-hop headers such as `Connection`), query parameters, and request body when applicable (e.g. for POSTs) will be proxied through.
* Can simulate creation of resources for cases where we do not wish to proxy the request to a "real" service where creation might have undesirable side effects, and instead wish to simply simulate a realistic flow of creating a new resource. This is powered by the same mixin functionality that's used by the other strategies for simulating creation.
* Rules can also match on headers, query parameters and the request body, serve `file:///` Jinja fixtures, and stamp every response with `X-Mockstack-Result` and `X-Mockstack-Rule`. See the [ProxyRules](https://promptromp.github.io/mockstack/strategies/proxyrules/) reference and the [ProxyRules cookbook](https://promptromp.github.io/mockstack/guides/proxyrules-cookbook/).
