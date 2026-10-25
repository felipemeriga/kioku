import { ConversationsContext } from "../hooks/ConversationsContext";
import { useConversations } from "../hooks/useConversations";
import { useAuth } from "../hooks/useAuth";

export default function ConversationsProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { user } = useAuth();
  return (
    <AccountConversations key={user?.id ?? "signed-out"}>
      {children}
    </AccountConversations>
  );
}

function AccountConversations({ children }: { children: React.ReactNode }) {
  const conversations = useConversations();
  return (
    <ConversationsContext.Provider value={conversations}>
      {children}
    </ConversationsContext.Provider>
  );
}
