// The whole page: sign-in, set-password, or the board, depending on who's signed in.
import { Login, SetPassword } from "./components/Auth";
import { BoardView, Summary } from "./components/Board";
import { AlertsView, Banner, CardActions, MeView, TabBar, TopBar } from "./components/Chrome";
import { NewTaskForm, PasswordForm, PeopleDialog } from "./components/Dialogs";
import { Modal } from "./components/Modal";
import { BellPanel, NotificationSettings, Toasts } from "./components/Notifications";
import { TaskDrawer } from "./components/TaskDrawer";
import { me, modal } from "./state";

export function App() {
  const user = me.value;
  let page = null;
  if (user === null) page = <Login />;
  else if (user && user.must_change_password) page = <SetPassword name={user.name} />;
  else if (user) {
    page = (
      <>
        <TopBar />
        <BellPanel />
        <Toasts />
        <main>
          <Summary />
          <BoardView />
          <AlertsView />
          <MeView />
        </main>
        <TabBar />
        <CardActions />
        <TaskDrawer />
        <Modal name="new-task">
          <NewTaskForm />
        </Modal>
        <Modal name="password">
          <PasswordForm />
        </Modal>
        <Modal name="notif-settings">
          <NotificationSettings />
          <div class="row end">
            <CloseDone />
          </div>
        </Modal>
        {user.is_admin && (
          <Modal name="people" wide>
            <PeopleDialog />
          </Modal>
        )}
      </>
    );
  }
  return (
    <>
      <Banner />
      {page}
    </>
  );
}

function CloseDone() {
  return (
    <button class="btn" type="button" onClick={() => (modal.value = null)}>
      Done
    </button>
  );
}
