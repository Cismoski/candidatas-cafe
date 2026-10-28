import { useAuth } from "./auth/AuthProvider";
import { LoginScreen } from "./components/LoginScreen";
import { Workspace } from "./components/Workspace";

export function App() {
  const { user } = useAuth();
  // key: troca de usuário remonta tudo (nenhum estado de tela vaza entre contas)
  return user ? <Workspace key={user.id} /> : <LoginScreen />;
}
