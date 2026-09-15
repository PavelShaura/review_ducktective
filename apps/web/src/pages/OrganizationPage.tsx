import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { ApiError, api } from "@/api/client";
import type { CurrentUser, Invitation, IssuedInvitation, Member, TenantRole } from "@/api/types";
import { formatDateTime } from "@/lib/format";

const ROLE_LABEL: Record<TenantRole, string> = {
  owner: "владелец",
  member: "участник",
};

/** Состав организации: кто в ней есть и кого позвали. */
export default function OrganizationPage() {
  const currentUser = useQuery({ queryKey: ["current-user"], queryFn: api.getCurrentUser });
  const members = useQuery({ queryKey: ["members"], queryFn: api.listMembers });

  if (currentUser.isPending || members.isPending) {
    return <p className="case-label py-16 text-center">поднимаю дело организации…</p>;
  }

  if (currentUser.isError || members.isError) {
    return <p className="py-20 text-center text-paper-dim">Сервис не отвечает.</p>;
  }

  const user: CurrentUser = currentUser.data;
  const isOwner = user.member?.role === "owner";

  return (
    <div className="space-y-12">
      <header>
        <h1 className="font-display text-3xl font-semibold text-paper">
          {user.organization?.name ?? "Организация"}
        </h1>
        <p className="case-label mt-2">
          {user.organization?.slug}
          {user.member ? ` · вы ${ROLE_LABEL[user.member.role]}` : ""}
        </p>
      </header>

      <MemberTable members={members.data} currentUserId={user.member?.id} isOwner={isOwner} />
      {isOwner ? <Invitations /> : null}
    </div>
  );
}

function MemberTable({
  members,
  currentUserId,
  isOwner,
}: {
  members: Member[];
  currentUserId: string | undefined;
  isOwner: boolean;
}) {
  const queryClient = useQueryClient();
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["members"] });

  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: string; role: TenantRole }) =>
      api.changeMemberRole(id, role),
    onSuccess: refresh,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api.removeMember(id),
    onSuccess: refresh,
  });

  return (
    <section className="space-y-4">
      <h2 className="font-display text-xl text-paper">Участники</h2>
      <ul className="divide-y divide-tweed-dim rounded-case border border-tweed-dim bg-ink-raised">
        {members.map((member) => (
          <li key={member.id} className="flex items-center justify-between gap-4 px-5 py-3">
            <span className="min-w-0">
              <span className="block truncate text-paper">{member.email}</span>
              <span className="case-label">
                {ROLE_LABEL[member.role]}
                {member.last_seen_at ? ` · был ${formatDateTime(member.last_seen_at)}` : ""}
              </span>
            </span>
            {isOwner && member.id !== currentUserId ? (
              <span className="flex shrink-0 items-center gap-3">
                <button
                  type="button"
                  onClick={() =>
                    changeRole.mutate({
                      id: member.id,
                      role: member.role === "owner" ? "member" : "owner",
                    })
                  }
                  className="case-label text-paper-dim hover:text-brass"
                >
                  {member.role === "owner" ? "сделать участником" : "сделать владельцем"}
                </button>
                <button
                  type="button"
                  onClick={() => remove.mutate(member.id)}
                  className="case-label text-paper-dim hover:text-critical"
                >
                  исключить
                </button>
              </span>
            ) : null}
          </li>
        ))}
      </ul>
      <Failure error={changeRole.error ?? remove.error} />
    </section>
  );
}

function Invitations() {
  const queryClient = useQueryClient();
  const invitations = useQuery({ queryKey: ["invitations"], queryFn: api.listInvitations });
  const [email, setEmail] = useState("");
  const [issued, setIssued] = useState<IssuedInvitation | null>(null);

  const invite = useMutation({
    mutationFn: () => api.inviteMember(email.trim(), "member"),
    onSuccess: (invitation) => {
      setIssued(invitation);
      setEmail("");
      void queryClient.invalidateQueries({ queryKey: ["invitations"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (id: string) => api.revokeInvitation(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["invitations"] }),
  });

  return (
    <section className="space-y-4">
      <h2 className="font-display text-xl text-paper">Приглашения</h2>

      <div className="flex flex-wrap items-end gap-3">
        <label className="min-w-64 flex-1 space-y-2">
          <span className="case-label">почтовый адрес</span>
          <input
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="colleague@example.com"
            spellCheck={false}
            className="w-full rounded-case border border-tweed-dim bg-ink-sunken px-3 py-2 font-mono text-[14px] text-paper placeholder:text-paper-dim/50"
          />
        </label>
        <button
          type="button"
          disabled={invite.isPending || !email.trim()}
          onClick={() => invite.mutate()}
          className="case-label rounded-case border border-tweed-dim px-4 py-2 text-paper hover:text-brass disabled:opacity-40"
        >
          {invite.isPending ? "выписываю…" : "пригласить"}
        </button>
      </div>

      {issued ? <IssuedToken invitation={issued} /> : null}
      <Failure error={invite.error ?? revoke.error} />

      {invitations.data && invitations.data.length > 0 ? (
        <ul className="divide-y divide-tweed-dim rounded-case border border-tweed-dim bg-ink-raised">
          {invitations.data.map((invitation: Invitation) => (
            <li key={invitation.id} className="flex items-center justify-between gap-4 px-5 py-3">
              <span className="min-w-0">
                <span className="block truncate text-paper">{invitation.email}</span>
                <span className="case-label">
                  действует до {formatDateTime(invitation.expires_at)}
                </span>
              </span>
              <button
                type="button"
                onClick={() => revoke.mutate(invitation.id)}
                className="case-label shrink-0 text-paper-dim hover:text-critical"
              >
                отозвать
              </button>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-paper-dim">Никого не ждём.</p>
      )}
    </section>
  );
}

/**
 * Секрет приглашения показывается один раз.
 *
 * В базе лежит только отпечаток: восстановить ссылку нельзя даже владельцу,
 * и об этом надо сказать прямо, пока код на экране.
 */
function IssuedToken({ invitation }: { invitation: IssuedInvitation }) {
  return (
    <div className="space-y-2 rounded-case border border-brass/50 bg-ink-sunken p-4">
      <p className="case-label">код для {invitation.email} — виден только сейчас</p>
      <code className="block break-all font-mono text-[13px] text-brass">{invitation.token}</code>
      <p className="text-paper-dim">
        Передайте его вместе со ссылкой на вход. Второй раз показать не получится —
        в базе хранится только отпечаток.
      </p>
    </div>
  );
}

function Failure({ error }: { error: unknown }) {
  if (!error) {
    return null;
  }

  const message =
    error instanceof ApiError
      ? error.status === 409
        ? "Так организация останется без владельца — или приглашение уже выписано."
        : error.message
      : "Сервис не отвечает.";
  return <p className="text-critical">{message}</p>;
}
