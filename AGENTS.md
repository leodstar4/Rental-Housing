<!-- LOVABLE:BEGIN -->
> [!IMPORTANT]
> This project is connected to [Lovable](https://lovable.dev). Avoid rewriting
> published git history — force pushing, or rebasing/amending/squashing commits
> that are already pushed — as it rewrites history on Lovable's side and the
> user will likely lose their project history.
>
> Commits you push to the connected branch sync back to Lovable and show up in
> the editor, so keep the branch in a working state.
<!-- LOVABLE:END -->

- Keep date values in ISO format for API requests; format only separate date fields for display and never rewrite text returned by the API, since it is already localized via `lang`.
- Own address selection and search text together in the lookup page; hide previous-address results during a new selection to prevent mismatched addresses.
