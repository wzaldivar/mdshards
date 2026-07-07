/**
 * The user who initiates a rename will be force-disconnected with the same
 * `DOC_MOVED_CODE` close as everyone else attached to the old doc. The
 * difference is they already know where they're going — they shouldn't see
 * the "follow?" banner. The RenameSwitcher adds the destination to this set
 * before POSTing the move; the Editor's close handler checks the set and
 * silently lets the navigation it already kicked off complete instead of
 * surfacing a notification.
 */
export const pendingRenames = new Set<string>()
