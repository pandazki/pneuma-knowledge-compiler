/** Display only what the profile's declared provenance establishes. */
export function profilePresentation(source: string) {
  const description = source === "mock"
    ? "profile.header.synthesizedDescription"
    : source === "user"
      ? "profile.header.savedDescription"
      : source === "unstated"
        ? "profile.header.unstatedDescription"
        : "profile.header.description";
  return { description, synthetic: source === "mock" } as const;
}
