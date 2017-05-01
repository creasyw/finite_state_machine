import collections
import functools
import inspect
import itertools
import logging


logger = logging.getLogger(__name__)


def listify(obj):
    if obj is None:
        return []
    else:
        return obj if isinstance(obj, (list, tuple, type(None))) else [obj]


class MachineError(DNSForwarderException):
    """Raised when the state machine fails to transit from one state to another"""
    def __init__(self, value):
        self.value = value

    def __str__(self):
        return repr(self.value)


class State(object):
    """Description of the status of a system"""

    def __init__(self, name, on_enter=None, on_exit=None):
        """
        :param name: String. The name of the state
        :param on_enter: String or list. Optional callable(s) to trigger when a state is entered.
                         Can be either a string providing the name of a callable, or a list of strings.
        :param on_exit: String or list. Optional callable(s) to trigger when a state is exited. Can
                        be either a string providing the name of a callable, or a list of strings.

        """
        self.name = name
        self.on_enter = listify(on_enter) if on_enter else []
        self.on_exit = listify(on_exit) if on_exit else []

    def __repr__(self):
        return "<%s('%s')@%s>" % (type(self).__name__, self.name, id(self))

    def enter(self, event, *args, **kwargs):
        """ Triggered when a state is entered. """
        logger.debug("Entering state %s. Processing callbacks...", self.name)
        for oe in self.on_enter:
            event.machine.trigger_callback(oe, *args, **kwargs)
        logger.info("Entered state %s", self.name)

    def exit(self, event, *args, **kwargs):
        """ Triggered when a state is exited. """
        logger.debug("Exiting state %s. Processing callbacks...", self.name)
        for oe in self.on_exit:
            event.machine.trigger_callback(oe, *args, **kwargs)
        logger.info("Exited state %s", self.name)

    def add_callback(self, trigger, func):
        """
        Add a new enter or exit callback.

        :param trigger: string. The type of triggering event. Must be one of 'enter' or 'exit'.
        :param func: string. The name of the callback function.
        """
        callback_list = getattr(self, trigger)
        callback_list.append(func)


class Condition(object):
    """Criterion to trigger the transition from a state to another"""

    def __init__(self, func):
        """
        :param func: String. Name of the condition-checking callable
        """
        self.func = func

    def __repr__(self):
        return "<%s(%s)@%s>" % (type(self).__name__, self.func, id(self))

    def check(self, event, target=True):
        """
        Check whether the condition passes.

        :param event: Event object.
        :param target: Boolean. Indicates the target state--i.e., when True, the condition-checking
                       callback should return True to pass, and when False, the callback should return
                       False to pass.
        """
        predicate = getattr(event.model, self.func) if isinstance(self.func, str) else self.func

        return predicate() == target


class Transition(object):
    """A set of actions to be executed when a condition is fulfilled or when an event is received"""

    def __init__(self, source, dest, conditions=None):
        """
        :param source: String. The name of the source State.
        :param dest: String. The name of the destination State.
        :param conditions: String or list. Condition(s) that must pass in order for the transition to
                           take place. Either a string providing the name of a callable, or a list of
                           callables. For the transition to occur, ALL callables must return True.
        """
        self.source = source
        self.dest = dest

        self.conditions = []
        if conditions is not None:
            for c in listify(conditions):
                self.conditions.append(Condition(c))

    def __repr__(self):
        return "<{}('{}', '{}')@{}>".format(type(self).__name__, self.source, self.dest, id(self))

    def execute(self, event, *args, target=True, **kwargs):
        """
        Execute the transition.

        :param event: An instance of class EventData.
        :return: Boolean, indicating whether or not the transition was successfully executed
        """
        logger.debug("Initiating transition from state %s to state %s...", self.source, self.dest)

        for c in self.conditions:
            if not c.check(event, target):
                logger.debug("Transition condition failed: %s(). Transition halted.", c.func)
                return False

        event.machine.get_state(self.source).exit(event, *args, **kwargs)
        event.machine.set_state(self.dest)
        event.machine.get_state(self.dest).enter(event, *args, **kwargs)
        return True


class Event(object):
    """A trigger that drive the transition of the system from one state to another"""

    def __init__(self, name, machine, model):
        """
        :param name: String. The name of the event, which is also the name of the triggering
                     callable (e.g., 'advance' implies an advance() method).
        :param machine: Machine object. The current Machine instance.
        :param model: The current model that is operated as a finite-states machine
        """
        self.name = name
        self.machine = machine
        self.model = model
        self.transitions = collections.defaultdict(list)

    def __repr__(self):
        return "<%s('%s')@%s>" % (type(self).__name__, self.name, id(self))

    def add_transition(self, transition):
        """
        Add a transition to the list of potential transitions.
        
        :param transition: Transition object. The Transition instance to add to the list.
        """
        self.transitions[transition.source].append(transition)

    def trigger(self, model, *args, **kwargs):
        f = functools.partial(self._trigger, model, *args, **kwargs)
        return f()

    def _trigger(self, model, *args, **kwargs):
        """
        Serially execute all transitions that match the current state

        :param args and kwargs: Optional positional or named arguments that will be passed onto the
                                EventData object, enabling arbitrary state information to be passed
                                on to downstream triggered functions.
        :return: boolean indicating whether or not a transition was successfully executed
        """
        state = self.machine.get_state(model.state)
        if state.name not in self.transitions:
            msg = "Can't trigger event %s from state %s!" % (self.name, state.name)
            raise MachineError(msg)

        try:
            for t in self.transitions[state.name]:
                if t.execute(self, *args, **kwargs):
                    return True
        except Exception as e:
            raise e


class Machine(object):
    """An abstract finite-state machine"""

    # Callback naming parameters
    callbacks = ['on_enter', 'on_exit']
    separator = '_'

    def __init__(self, states, initial, model):
        """
        :param states: A list of valid states. Each element can be either a string or a State
                       instance. If string, it's preferrable to have the name without whitespace,
                       so that the callback functions can be concatenated with on_enter or on_exit.
                       A new generic State instance will be created that has the same name as the string.
        :param initial: String. The initial state of the Machine.
        :param model: The instantiated object that is operated as a finite-states machine
        """
        self.states = collections.OrderedDict()
        self.events = {}
        self.model = model

        for state in states:
            self.add_state(state)

        if initial not in self.states:
            self.add_state(initial)

        self._initial = initial

        # Register a model with the state machine, initializing triggers and callbacks.
        if hasattr(self.model, 'trigger'):
            logger.warning("%sModel already contains an attribute 'trigger'. Skip method binding ")
        else:
            self.model.trigger = functools.partial(self._get_trigger, self.model)

        for trigger, _ in self.events.items():
            self._add_trigger_to_model(trigger)

        for _, state in self.states.items():
            self._add_model_to_state(state)

        self.set_state(self._initial)

    @staticmethod
    def _get_trigger(model, trigger_name, *args, **kwargs):
        func = getattr(model, trigger_name, None)
        if func:
            return func(*args, **kwargs)
        raise AttributeError("Model has no trigger named '%s'" % trigger_name)

    @staticmethod
    def _create_transition(*args, **kwargs):
        return Transition(*args, **kwargs)

    @staticmethod
    def _create_event(*args, **kwargs):
        return Event(*args, **kwargs)

    @staticmethod
    def _create_state(*args, **kwargs):
        return State(*args, **kwargs)

    @property
    def initial(self):
        """Return the initial state. """
        return self._initial

    def is_state(self, state, model):
        """Check whether the current state matches the named state. """
        return model.state == state

    def get_state(self, state):
        """Return the State instance with the passed name. """
        if state not in self.states:
            raise ValueError("State '%s' is not a registered state." % state)
        return self.states[state]

    def set_state(self, state):
        """Set the current state. """
        if isinstance(state, str):
            state = self.get_state(state)
        self.model.state = state.name

    def _add_model_to_state(self, state):
        setattr(self.model, 'is_%s' % state.name, functools.partial(self.is_state, state.name, self.model))
        #  Add enter/exit callbacks if there are existing bound methods
        enter_callback = 'on_enter_' + state.name
        if hasattr(self.model, enter_callback) and inspect.ismethod(getattr(self.model, enter_callback)):
            state.add_callback('on_enter', enter_callback)
        exit_callback = 'on_exit_' + state.name
        if hasattr(self.model, exit_callback) and inspect.ismethod(getattr(self.model, exit_callback)):
            state.add_callback('on_exit', exit_callback)


    def _add_trigger_to_model(self, trigger):
        trig_func = functools.partial(self.events[trigger].trigger, self.model)
        setattr(self.model, trigger, trig_func)

    def add_state(self, state, on_enter=None, on_exit=None):
        """
        Add new state

        :param state: A string, alist of string, a State instance, or a dict with keywords to pass
                      on to the State initializer.
        :param on_enter: String or list. Callbacks to trigger when the state is entered. Only valid
                         if first argument is string.
        :param on_exit: String or list. Callbacks to trigger when the state is exited. Only valid
                        if first argument is string.
        """
        if isinstance(state, str):
            state = self._create_state(state, on_enter=on_enter, on_exit=on_exit)
        elif isinstance(state, dict):
            state = self._create_state(**state)
        self.states[state.name] = state
        self._add_model_to_state(state)

    def get_triggers(self, states):
        """
        Get the transitions that are valid for given states

        :param states: List of states
        """
        return [t for (t, ev) in self.events.items() if any(state in ev.transitions for state in states)]

    def add_transition(self, trigger, source, dest, *args, conditions=None):
        """
        Create a new Transition instance and add it to the internal list.

        :param trigger: String. The name of the method that will trigger the transition. This will
                        be attached to the currently specified model
        :param source: String. The name of the state that the model is transitioning away from.
        :param dest: String. The name of the state that the model is transitioning into
        :param conditions: String or list. Condition(s) that must pass in order for the transition
                           to take place. Either a list providing the name of a callable, or a list
                           of callables. For the transition to occur, ALL callables must return True.
        """
        if trigger not in self.events:
            self.events[trigger] = self._create_event(trigger, self, self.model)
            self._add_trigger_to_model(trigger)

        t = self._create_transition(source, dest, conditions)
        self.events[trigger].add_transition(t)

    def trigger_callback(self, func, *args, **kwargs):
        """
        Trigger a callback function, possibly wrapping it in an EventData instance.

        :param func: The callback function.
        :param args and kwargs: Optional positional or named arguments that will be passed onto the
                                EventData object, enabling arbitrary state information to be passed
                                on to downstream triggered functions.
        """
        if isinstance(func, str):
            func = getattr(self.model, func)
        func(*args, **kwargs)
