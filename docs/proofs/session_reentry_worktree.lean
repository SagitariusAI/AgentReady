/-
AgentReady session re-entry checkout-selection invariant.

`repoIdentity` represents the physical Git common-directory identity. A task
without an isolated worktree selects the canonical checkout. A task that names
a worktree selects it only when its identity equals the repository identity;
otherwise selection fails closed.
-/

def selectCheckout
    (repoIdentity : Nat)
    (taskWorktreeIdentity : Option Nat) : Option Nat :=
  match taskWorktreeIdentity with
  | none => some repoIdentity
  | some identity =>
      if identity = repoIdentity then some identity else none

theorem canonical_checkout_is_selected_without_a_task_worktree
    (repoIdentity : Nat) :
    selectCheckout repoIdentity none = some repoIdentity := by
  rfl

theorem mismatched_task_worktree_is_rejected
    (repoIdentity worktreeIdentity : Nat)
    (different : worktreeIdentity ≠ repoIdentity) :
    selectCheckout repoIdentity (some worktreeIdentity) = none := by
  simp [selectCheckout, different]

theorem every_selected_checkout_preserves_repository_identity
    (repoIdentity selectedIdentity : Nat)
    (taskWorktreeIdentity : Option Nat)
    (selected : selectCheckout repoIdentity taskWorktreeIdentity = some selectedIdentity) :
    selectedIdentity = repoIdentity := by
  cases taskWorktreeIdentity <;> simp_all [selectCheckout]

def MINIMUM_RECEIPT_TTL_MINUTES : Nat := 1
def DEFAULT_RECEIPT_TTL_MINUTES : Nat := 240
def SECONDS_PER_MINUTE : Nat := 60

def receiptTtlMinutes (requested : Nat) : Nat :=
  max MINIMUM_RECEIPT_TTL_MINUTES requested

theorem every_receipt_lifetime_is_positive (requested : Nat) :
    0 < receiptTtlMinutes requested := by
  unfold receiptTtlMinutes MINIMUM_RECEIPT_TTL_MINUTES
  exact Nat.lt_of_lt_of_le (by decide : 0 < 1) (Nat.le_max_left 1 requested)

theorem default_receipt_lifetime_is_four_hours :
    receiptTtlMinutes DEFAULT_RECEIPT_TTL_MINUTES * SECONDS_PER_MINUTE =
      4 * 60 * 60 := by
  decide
